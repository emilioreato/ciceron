using System;
using System.Diagnostics;
using System.IO;
using System.Reflection;
using System.Windows.Forms;

internal static class CiceronLauncher
{
    private static string Quote(string value)
    {
        // Windows argv quoting, including runs of backslashes before a quote.
        return "\"" + System.Text.RegularExpressions.Regex.Replace(value, "(\\\\*)(\"|$)",
            m => m.Groups[1].Value + m.Groups[1].Value + (m.Groups[2].Value == "\"" ? "\\\"" : "")) + "\"";
    }

    private static void Relay(Stream source, Stream target)
    {
        var buffer = new byte[8192];
        int count;
        while ((count = source.Read(buffer, 0, buffer.Length)) != 0)
        {
            target.Write(buffer, 0, count);
            target.Flush();
        }
    }

    private static Process Start(Func<ProcessStartInfo> configure, string sessionFile, bool reload)
    {
        using (var maintenance = new System.Threading.Mutex(false, @"Local\CiceronInstalacion"))
        {
            bool ready;
            try { ready = maintenance.WaitOne(reload ? 250 : 10000); }
            catch (System.Threading.AbandonedMutexException) { ready = true; }
            if (!ready && reload) return null;
            if (!ready) throw new InvalidOperationException("Hay una instalación de Cicerón en curso.");
            try
            {
                var process = Process.Start(configure());
                if (sessionFile != null)
                {
                    // Wait for Python to register the session before allowing an update.
                    var wait = Stopwatch.StartNew();
                    while (wait.ElapsedMilliseconds < 4000 && !process.HasExited && !SessionRegistered(sessionFile))
                        System.Threading.Thread.Sleep(25);
                }
                return process;
            }
            finally { maintenance.ReleaseMutex(); }
        }
    }

    private static bool SessionRegistered(string path)
    {
        if (!File.Exists(path)) return false;
        try { using (File.Open(path, FileMode.Open, FileAccess.ReadWrite, FileShare.None)) { return false; } }
        catch (IOException) { return true; }
    }

    private static ProcessStartInfo Configure(string root, bool host, string[] args)
    {
        string code = Path.Combine(root, "_internal");
        string key = File.ReadAllText(Path.Combine(code, "entorno.txt")).Trim();
        if (!System.Text.RegularExpressions.Regex.IsMatch(key, @"\A[a-f0-9]{64}\z"))
            throw new InvalidDataException("La referencia al entorno de Python es inválida.");
        string environment = Path.Combine(root, ".entornos", key);
        string location = File.ReadAllText(Path.Combine(environment, "ubicacion.txt")).Trim();
        if (!String.Equals(environment, location, StringComparison.OrdinalIgnoreCase))
            throw new InvalidOperationException("La carpeta de Cicerón se movió. Ejecuta Reparar integracion.bat.");
        string entry = Path.Combine(code, "src", host ? "browser_bridge.py" : "ciceron.pyw");
        string bootstrap = Path.Combine(code, "ejecutar_fuentes.py");
        if (!host && File.Exists(bootstrap)) entry = bootstrap;
        return new ProcessStartInfo
        {
            FileName = Path.Combine(environment, "Scripts", host ? "python.exe" : "pythonw.exe"),
            WorkingDirectory = root,
            Arguments = "-E -s -B " + Quote(entry)
                + (args.Length == 0 ? "" : " " + String.Join(" ", Array.ConvertAll(args, Quote))),
            UseShellExecute = false,
            CreateNoWindow = true,
            RedirectStandardInput = host,
            RedirectStandardOutput = host
        };
    }

    private static int Main(string[] args)
    {
        string exe = Assembly.GetExecutingAssembly().Location;
        string root = Path.GetDirectoryName(exe);
        bool host = Path.GetFileName(exe).StartsWith("CiceronHost", StringComparison.OrdinalIgnoreCase);
        try
        {
            string session = host ? null : Path.Combine(root, "centro-fuentes.lock");
            bool reload = !host && Array.IndexOf(args, "--ciceron-recarga") >= 0;
            using (var process = Start(() => Configure(root, host, args), session, reload))
            {
                if (process == null) return 0;
                if (!host)
                {
                    if (process.HasExited && process.ExitCode != 0)
                        throw new InvalidOperationException("Python no pudo iniciar Cicerón. Ejecuta Instalar.bat para revisar el entorno.");
                    return 0;
                }
                var input = new System.Threading.Thread(() =>
                {
                    using (var pipe = process.StandardInput.BaseStream)
                    {
                        try { Relay(Console.OpenStandardInput(), pipe); }
                        catch (IOException) { }
                    }
                });
                input.IsBackground = true;
                input.Start();
                try { Relay(process.StandardOutput.BaseStream, Console.OpenStandardOutput()); }
                catch (IOException) { if (!process.HasExited) process.Kill(); }
                process.WaitForExit();
                return process.ExitCode;
            }
        }
        catch (Exception error)
        {
            if (host) Console.Error.WriteLine(error.Message);
            else MessageBox.Show(error.Message, "Cicerón", MessageBoxButtons.OK, MessageBoxIcon.Warning);
            return 1;
        }
    }
}
