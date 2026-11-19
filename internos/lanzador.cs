using System;
using System.Diagnostics;
using System.IO;
using System.Reflection;
using System.Windows.Forms;

internal static class CiceronLauncher
{
    private sealed class RepairRequired : Exception
    {
        public readonly bool Moved;
        public RepairRequired(string message, bool moved = false) : base(message) { Moved = moved; }
    }

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
        string marker = Path.Combine(environment, "ubicacion.txt");
        string interpreter = Path.Combine(environment, "Scripts", host ? "python.exe" : "pythonw.exe");
        if (!File.Exists(marker) || !File.Exists(interpreter))
            throw new RepairRequired("Falta parte del entorno de Python de Cicerón.");
        string location = File.ReadAllText(marker).Trim();
        if (!String.Equals(environment, location, StringComparison.OrdinalIgnoreCase))
            throw new RepairRequired("La carpeta de Cicerón se movió.", true);
        string entry = Path.Combine(code, "src", host ? "browser_bridge.py" : "ciceron.pyw");
        string bootstrap = Path.Combine(code, "ejecutar_fuentes.py");
        if (!host && File.Exists(bootstrap)) entry = bootstrap;
        return new ProcessStartInfo
        {
            FileName = interpreter,
            WorkingDirectory = root,
            Arguments = "-E -s -B " + Quote(entry)
                + (args.Length == 0 ? "" : " " + String.Join(" ", Array.ConvertAll(args, Quote))),
            UseShellExecute = false,
            CreateNoWindow = true,
            RedirectStandardInput = host,
            RedirectStandardOutput = host
        };
    }

    private static bool Repair(string root)
    {
        string script = Path.Combine(root, "integracion", "instalar.ps1");
        if (!File.Exists(script)) return false;
        string shell = Path.Combine(Environment.SystemDirectory, "WindowsPowerShell", "v1.0", "powershell.exe");
        var info = new ProcessStartInfo(shell, "-NoProfile -ExecutionPolicy Bypass -File "
            + Quote(script) + " -InstallDir " + Quote(root) + " -Reparar") { WorkingDirectory = root };
        using (var process = Process.Start(info))
        {
            process.WaitForExit();
            return process.ExitCode == 0;
        }
    }

    private static int OpenCenter(string root, string[] args)
    {
        string session = Path.Combine(root, "centro-fuentes.lock");
        bool reload = Array.IndexOf(args, "--ciceron-recarga") >= 0;
        for (int attempt = 0; ; attempt++)
        {
            try
            {
                using (var process = Start(() => Configure(root, false, args), session, reload))
                {
                    if (process != null && process.HasExited && process.ExitCode != 0)
                        throw new RepairRequired("Python no pudo iniciar Cicerón.");
                    return 0;
                }
            }
            catch (RepairRequired error)
            {
                if (attempt != 0 || reload) throw;
                if (!error.Moved && MessageBox.Show(error.Message + "\n\n¿Quieres intentar reparar el entorno?",
                    "Cicerón", MessageBoxButtons.YesNo, MessageBoxIcon.Warning) != DialogResult.Yes)
                    return 1;
                if (!Repair(root))
                    throw new InvalidOperationException("No se completó la reparación. Abre Reparar integracion.bat para ver el detalle.");
            }
        }
    }

    private static int Main(string[] args)
    {
        string exe = Assembly.GetExecutingAssembly().Location;
        string root = Path.GetDirectoryName(exe);
        bool host = Path.GetFileName(exe).StartsWith("CiceronHost", StringComparison.OrdinalIgnoreCase);
        try
        {
            if (!host) return OpenCenter(root, args);
            using (var process = Start(() => Configure(root, true, args), null, false))
            {
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
