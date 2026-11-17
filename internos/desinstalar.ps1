param(
    [string]$RunKey = 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Run',
    [string]$NativeRoot = 'HKCU:\Software',
    [switch]$Confirmar
)
$ErrorActionPreference = 'Stop'
$installDir = Join-Path $env:LOCALAPPDATA 'GanaLaBatalla'
$destination = Join-Path $installDir 'Ciceron.exe'
$legacyExe = Join-Path $installDir 'GanaLaBatalla.exe'
$menu = Join-Path $env:APPDATA 'Microsoft\Windows\Start Menu\Programs'
$mutex = New-Object System.Threading.Mutex($false, 'Local\CiceronInstalacion')
$locked = $false
try {
    try { $locked = $mutex.WaitOne(0) } catch [System.Threading.AbandonedMutexException] { $locked = $true }
    if (!$locked) { throw 'Ya hay una instalación o desinstalación en curso. Espera a que termine.' }
    $running = @(Get-Process -Name 'Ciceron','GanaLaBatalla' -ErrorAction SilentlyContinue | Where-Object { $_.Path -eq $destination -or $_.Path -eq $legacyExe })
    if (!$Confirmar) {
        $question = 'Se quitarán Cicerón y su inicio automático. La configuración personal se conservará.'
        if ($running.Count -gt 0) { $question += ' Se cerrará la aplicación y se perderán los cambios no guardados.' }
        $answer = Read-Host ($question + ' Escribe SI para continuar')
        if ($answer -cne 'SI') { Write-Host 'Desinstalación cancelada.'; exit 0 }
    }
    foreach ($process in $running) { Stop-Process -Id $process.Id -Force -ErrorAction SilentlyContinue }
    foreach ($process in $running) { try { $process.WaitForExit(5000) | Out-Null } catch [System.InvalidOperationException] { } }
    $remaining = @(Get-Process -Name 'Ciceron','GanaLaBatalla' -ErrorAction SilentlyContinue | Where-Object { $_.Path -eq $destination -or $_.Path -eq $legacyExe })
    if ($remaining.Count -gt 0) { throw 'No se pudo cerrar Cicerón; sus archivos y el inicio automático se conservan' }
    if (Test-Path -LiteralPath $RunKey) {
        $entry = Get-ItemProperty -LiteralPath $RunKey -Name GanaLaBatalla -ErrorAction SilentlyContinue
        if ($null -ne $entry -and $entry.GanaLaBatalla -is [string]) {
            $target = $entry.GanaLaBatalla.Trim().Trim('"')
            if ($target -eq $destination -or $target -eq $legacyExe) { Remove-ItemProperty -LiteralPath $RunKey -Name GanaLaBatalla }
            else { Write-Warning 'Se conservó una entrada de inicio con el mismo nombre porque apunta a otro programa.' }
        }
        elseif ($null -ne $entry) { Write-Warning 'Se conservó una entrada de inicio con formato desconocido.' }
    }
    $shell = New-Object -ComObject WScript.Shell
    foreach ($name in @('Mi centro.lnk','Gana la batalla.lnk')) {
        $link = Join-Path $menu $name
        if (Test-Path -LiteralPath $link) {
            $target = $shell.CreateShortcut($link).TargetPath
            if ($target -eq $destination -or $target -eq $legacyExe) { Remove-Item -LiteralPath $link -Force }
            else { Write-Warning "Se conservó el acceso $name porque apunta a otro programa." }
        }
    }
    $libraryLinks = Join-Path $menu 'Ciceron'
    $libraryDir = Get-Item -LiteralPath $libraryLinks -ErrorAction SilentlyContinue
    if ($libraryDir -and $libraryDir.PSIsContainer -and !($libraryDir.Attributes -band [IO.FileAttributes]::ReparsePoint)) {
        foreach ($file in Get-ChildItem -LiteralPath $libraryLinks -Filter '*.lnk' -File) {
            if (!($file.Attributes -band [IO.FileAttributes]::ReparsePoint) -and
                $shell.CreateShortcut($file.FullName).Description -cmatch '^Ciceron\.Library:[0-9a-f]{16} ') {
                Remove-Item -LiteralPath $file.FullName -Force
            }
        }
        if (!(Get-ChildItem -LiteralPath $libraryLinks -Force | Select-Object -First 1)) {
            Remove-Item -LiteralPath $libraryLinks
        }
    }
    $manifest = Join-Path $installDir 'ciceron-native-host.json'
    foreach ($vendor in @('Google\Chrome','Microsoft\Edge')) {
        $key = $NativeRoot + '\' + $vendor + '\NativeMessagingHosts\com.ciceron.browser'
        if (Test-Path -LiteralPath $key) {
            $item = Get-Item -LiteralPath $key
            if ($item.GetValue('') -eq $manifest) {
                if (!$key.StartsWith('HKCU:\',[StringComparison]::OrdinalIgnoreCase)) { throw 'Raíz del Registro no compatible.' }
                $writable=[Microsoft.Win32.Registry]::CurrentUser.OpenSubKey($key.Substring(6),$true)
                try { $writable.DeleteValue('', $false); $empty=$writable.GetValueNames().Count -eq 0 -and $writable.GetSubKeyNames().Count -eq 0 } finally { $writable.Dispose() }
                if ($empty) { Remove-Item -LiteralPath $key -Force }
            } else { Write-Warning 'Se conservó un registro de navegador que apunta a otro puente.' }
        }
    }
    $hosts = @(Get-Process -Name 'CiceronHost-*' -ErrorAction SilentlyContinue | Where-Object { $_.Path -and (Split-Path -Parent $_.Path) -eq $installDir -and (Split-Path -Leaf $_.Path) -match '^CiceronHost-[0-9a-f]{16}\.exe$' })
    foreach ($process in $hosts) { Stop-Process -Id $process.Id -Force -ErrorAction SilentlyContinue }
    foreach ($process in $hosts) { try { $process.WaitForExit(5000) | Out-Null } catch [System.InvalidOperationException] { } }
    foreach ($file in @(Get-ChildItem -LiteralPath $installDir -Filter 'CiceronHost-*.exe' -File -ErrorAction SilentlyContinue)) {
        if ($file.Name -match '^CiceronHost-[0-9a-f]{16}\.exe$') { Remove-Item -LiteralPath $file.FullName -Force }
    }
    if (Test-Path -LiteralPath $manifest) {
        try { $data=Get-Content -LiteralPath $manifest -Raw -Encoding UTF8 | ConvertFrom-Json } catch { $data=$null }
        if ($data.name -eq 'com.ciceron.browser' -and @($data.allowed_origins).Count -eq 1 -and @($data.allowed_origins)[0] -eq 'chrome-extension://cmbcmfhajdjlcepmkhjnfooadbccljpk/') { Remove-Item -LiteralPath $manifest -Force }
        else { Write-Warning 'Se conservó un manifiesto de navegador desconocido.' }
    }
    foreach ($path in @((Join-Path $installDir 'extension-path.txt'),$destination,$legacyExe,(Join-Path $installDir 'Ciceron.instalando.tmp'),(Join-Path $installDir 'Ciceron.respaldo.tmp'))) {
        if (Test-Path -LiteralPath $path) { Remove-Item -LiteralPath $path -Force }
    }
    if ((Test-Path -LiteralPath $installDir) -and @(Get-ChildItem -LiteralPath $installDir -Force).Count -eq 0) { Remove-Item -LiteralPath $installDir -Force }
    Write-Host 'Cicerón está desinstalado. Se conservó la configuración personal y la extensión cargada; puedes quitarla desde el navegador.'
} catch {
    Write-Host "No se pudo completar la desinstalación: $($_.Exception.Message). Puedes volver a ejecutar Desinstalar.bat."
    exit 1
} finally {
    if ($locked) { $mutex.ReleaseMutex() }
    $mutex.Dispose()
}
