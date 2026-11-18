param([string]$PackageRoot, [string]$InstallDir, [string]$RegistryRoot='HKCU:\Software')
$ErrorActionPreference='Stop'
$PackageRoot=[IO.Path]::GetFullPath($PackageRoot)
$InstallDir=[IO.Path]::GetFullPath($InstallDir)
$source=Join-Path $PackageRoot 'navegador\extension'
$hostSource=Join-Path $PackageRoot 'internos\CiceronHost.exe'
if (!(Test-Path -LiteralPath (Join-Path $source 'manifest.json')) -or !(Test-Path -LiteralPath $hostSource)) {
    Write-Warning 'El paquete no contiene la extensión o el puente nativo; la aplicación de escritorio sí puede funcionar.'
    exit 2
}
$browserRoot=$InstallDir
$extension=Join-Path $browserRoot '00 EXTENSION'
$token=[guid]::NewGuid().ToString('N')
$stage=Join-Path $browserRoot ('.preparando-'+$token)
$backup=Join-Path $browserRoot ('.anterior-'+$token)
$hostHash=(Get-FileHash -LiteralPath $hostSource -Algorithm SHA256).Hash.ToLowerInvariant()
$hostFile=Join-Path $InstallDir ('CiceronHost-'+$hostHash.Substring(0,16)+'.exe')
$hostManifest=Join-Path $InstallDir 'ciceron-native-host.json'
$legacyManifest=Join-Path (Join-Path $env:LOCALAPPDATA 'GanaLaBatalla') 'ciceron-native-host.json'
$previousManifest=Join-Path (Join-Path $env:LOCALAPPDATA 'Ciceron') 'ciceron-native-host.json'
$warnings=@()
try {
    $files=@('manifest.json','background.js','bridge.js','content.js','popup.js','popup.html','popup.css','rules.json')
    foreach ($name in $files) { if (!(Test-Path -LiteralPath (Join-Path $source $name) -PathType Leaf)) { throw "Falta el archivo de la extensión: $name" } }
    New-Item -ItemType Directory -Force -Path $InstallDir | Out-Null
    $previousExtension=Join-Path $PackageRoot '00 EXTENSION'
    if (!(Test-Path -LiteralPath $extension) -and (Test-Path -LiteralPath $previousExtension -PathType Container)) {
        $previousItem=Get-Item -LiteralPath $previousExtension -Force
        if ($previousItem.Attributes -band [IO.FileAttributes]::ReparsePoint) { throw 'La extensión anterior es un enlace; se conserva sin mover.' }
        foreach ($item in Get-ChildItem -LiteralPath $previousExtension -Force -Recurse) {
            if ($item.Attributes -band [IO.FileAttributes]::ReparsePoint) { throw "La extensión anterior contiene un enlace; se conserva: $($item.FullName)" }
        }
        Copy-Item -LiteralPath $previousExtension -Destination $browserRoot -Recurse
        foreach ($file in Get-ChildItem -LiteralPath $previousExtension -Force -Recurse -File) {
            $relative=$file.FullName.Substring($previousExtension.Length).TrimStart('\\')
            $copy=Join-Path $extension $relative
            if (!(Test-Path -LiteralPath $copy -PathType Leaf) -or (Get-FileHash -LiteralPath $file.FullName).Hash -ne (Get-FileHash -LiteralPath $copy).Hash) {
                throw "La copia de la extensión anterior no coincide: $relative"
            }
        }
    }
    if (Test-Path -LiteralPath $extension -PathType Container) {
        $allowed=$files+@('README.md','_metadata','icons')
        $unknown=@(Get-ChildItem -LiteralPath $extension -Force | Where-Object { $_.Name -notin $allowed })
        if ($unknown.Count -gt 0) { throw 'Hay archivos adicionales en la extensión instalada; se conservó la carpeta sin modificar.' }
    }
    New-Item -ItemType Directory -Force -Path $InstallDir,$browserRoot | Out-Null
    if (Test-Path -LiteralPath $hostFile) {
        if ((Get-FileHash -LiteralPath $hostFile -Algorithm SHA256).Hash.ToLowerInvariant() -ne $hostHash) { throw 'Ya existe un puente con el mismo nombre y contenido diferente.' }
    } else { Copy-Item -LiteralPath $hostSource -Destination $hostFile }
    $same=Test-Path -LiteralPath $extension -PathType Container
    if ($same) {
        foreach($name in $files) {
            $a=Join-Path $source $name; $b=Join-Path $extension $name
            if (!(Test-Path -LiteralPath $a -PathType Leaf) -or !(Test-Path -LiteralPath $b -PathType Leaf) -or (Get-FileHash -LiteralPath $a).Hash -ne (Get-FileHash -LiteralPath $b).Hash) { $same=$false; break }
        }
    }
    if (!$same) {
        New-Item -ItemType Directory -Path $stage | Out-Null
        foreach ($name in $files + @('README.md','icons')) {
            $entry = Join-Path $source $name
            if (Test-Path -LiteralPath $entry) {
                Copy-Item -LiteralPath $entry -Destination $stage -Recurse
            }
        }
        foreach($path in @($stage,$extension,$backup)) {
            if (![IO.Path]::GetFullPath($path).StartsWith([IO.Path]::GetFullPath($browserRoot)+'\',[StringComparison]::OrdinalIgnoreCase)) { throw 'Ruta de extensión fuera de la carpeta prevista.' }
        }
        if (Test-Path -LiteralPath $extension) { Move-Item -LiteralPath $extension -Destination $backup }
        try { Move-Item -LiteralPath $stage -Destination $extension }
        catch { if (Test-Path -LiteralPath $backup) { Move-Item -LiteralPath $backup -Destination $extension }; throw }
        if (Test-Path -LiteralPath $backup) {
            $resolved=(Resolve-Path -LiteralPath $backup).Path
            if ($resolved -ne $backup -or !$resolved.StartsWith([IO.Path]::GetFullPath($browserRoot)+'\',[StringComparison]::OrdinalIgnoreCase)) { throw 'Ruta de respaldo inesperada; no se elimina.' }
            Remove-Item -LiteralPath $resolved -Recurse -Force
        }
    }
    [IO.File]::WriteAllText((Join-Path $InstallDir 'extension-path.txt'),'00 EXTENSION',(New-Object System.Text.UTF8Encoding($false)))
    $hostData=@{name='com.ciceron.browser';description='Puente local de Cicerón';path=$hostFile;type='stdio';allowed_origins=@('chrome-extension://cmbcmfhajdjlcepmkhjnfooadbccljpk/')}
    $tempManifest=Join-Path $InstallDir ('manifest-'+$token+'.tmp')
    if (Test-Path -LiteralPath $hostManifest) {
        try { $existing=Get-Content -LiteralPath $hostManifest -Raw -Encoding UTF8 | ConvertFrom-Json }
        catch { throw 'El manifiesto anterior no se puede leer; no se sobrescribirá.' }
        if ($existing.name -ne 'com.ciceron.browser' -or @($existing.allowed_origins).Count -ne 1 -or @($existing.allowed_origins)[0] -ne 'chrome-extension://cmbcmfhajdjlcepmkhjnfooadbccljpk/') { throw 'El manifiesto existente pertenece a otra integración; no se sobrescribirá.' }
    }
    $json=$hostData | ConvertTo-Json -Depth 4
    [IO.File]::WriteAllText($tempManifest,$json,(New-Object System.Text.UTF8Encoding($false)))
    if (Test-Path -LiteralPath $hostManifest) {
        $manifestBackup=Join-Path $InstallDir ('manifest-'+$token+'.bak')
        [IO.File]::Replace($tempManifest,$hostManifest,$manifestBackup,$true)
        Remove-Item -LiteralPath $manifestBackup -Force
    } else { Move-Item -LiteralPath $tempManifest -Destination $hostManifest }
    $roots=@($env:ProgramFiles, ${env:ProgramFiles(x86)}, $env:LOCALAPPDATA) | Where-Object { $_ }
    $suffixes=@{ Chrome='Google\Chrome\Application\chrome.exe'; Brave='BraveSoftware\Brave-Browser\Application\brave.exe'; Edge='Microsoft\Edge\Application\msedge.exe' }
    $count=0
    foreach($browser in @('Chrome','Brave','Edge')) {
        $found=$false
        foreach($root in $roots) { if(Test-Path -LiteralPath (Join-Path $root $suffixes[$browser]) -PathType Leaf) { $found=$true; break } }
        if (!$found) { continue }
        $vendor=if($browser -eq 'Edge') {'Microsoft\Edge'} else {'Google\Chrome'}
        $key=$RegistryRoot+'\'+$vendor+'\NativeMessagingHosts\com.ciceron.browser'
        try {
            if(Test-Path -LiteralPath $key) {
                $current=(Get-Item -LiteralPath $key).GetValue('')
                if ($current -and $current -notin @($hostManifest,$legacyManifest,$previousManifest)) {
                    $owned=$false
                    try {
                        if (Test-Path -LiteralPath $current) {
                            $old=Get-Content -LiteralPath $current -Raw -Encoding UTF8 | ConvertFrom-Json
                            $oldHost=Split-Path -Leaf $old.path
                            $owned=$old.name -eq 'com.ciceron.browser' -and $old.type -eq 'stdio' -and
                                @($old.allowed_origins).Count -eq 1 -and @($old.allowed_origins)[0] -eq 'chrome-extension://cmbcmfhajdjlcepmkhjnfooadbccljpk/' -and
                                $oldHost -match '^CiceronHost-[0-9a-f]{16}\.exe$'
                        } else {
                            $owned=[IO.Path]::GetFileName($current) -ieq 'ciceron-native-host.json'
                        }
                    } catch { $owned=$false }
                    if (!$owned) { throw 'Ya existe otro puente con ese nombre.' }
                }
            }
            $entry=New-Item -Path $key -Force
            $entry.SetValue('', $hostManifest, [Microsoft.Win32.RegistryValueKind]::String)
            Write-Host "Puente preparado para $browser."
            $count++
        } catch { $warnings += "$browser : $($_.Exception.Message)" }
    }
    if ($count -eq 0) { $warnings += 'No se detectó un navegador compatible; puedes prepararlo después desde Cicerón.' }
    Write-Host "Extensión preparada en: $extension"
    Write-Host 'Aún debes cargarla manualmente en cada perfil del navegador; después desactiva la antigua Pausa Feed.'
    if ($warnings.Count -gt 0) { foreach($warning in $warnings){ Write-Warning $warning }; exit 2 }
} catch {
    Write-Warning "No se completó la preparación del navegador: $($_.Exception.Message)"
    exit 2
} finally {
    if (Test-Path -LiteralPath $stage) {
        $resolved=(Resolve-Path -LiteralPath $stage).Path
        if ($resolved -eq $stage -and $resolved.StartsWith([IO.Path]::GetFullPath($browserRoot)+'\',[StringComparison]::OrdinalIgnoreCase)) { Remove-Item -LiteralPath $resolved -Recurse -Force -ErrorAction SilentlyContinue }
    }
}
