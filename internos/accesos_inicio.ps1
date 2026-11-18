$builtInTools = @(
    @{ Id = 'clock'; Name = 'Timer y enfoque'; OldName = 'Timer y enfoque - Temporizador'; Aliases = [ordered]@{
        temporizador = 'Temporizador'; cuenta = 'Cuenta atrás'
    }; Tags = @('timer', 'enfoque', 'temporizador', 'cuenta atrás', 'exámenes', 'productividad') },
    @{ Id = 'browser'; Name = 'Pausa Feed'; OldName = 'Navegador - Pausa Feed'; Aliases = [ordered]@{
        navegador = 'Navegador'; bloqueo = 'Bloqueo'; twitter = 'Desactivar Twitter'
    }; Tags = @('navegador', 'pausa feed', 'bloqueo', 'desactivar Twitter', 'bloquear YouTube', 'redes sociales') },
    @{ Id = 'effects'; Name = 'Burbuja'; OldName = 'Efectos de escritorio - Liquid Glass'; Aliases = [ordered]@{
        particulas = 'Partículas'; vidrio = 'Liquid Glass'; efectos = 'Efectos de escritorio'
    }; Tags = @('burbuja', 'partículas', 'Liquid Glass', 'efectos de escritorio', 'lente', 'animación') }
)

function Get-CiceronToolShortcuts($tool) {
    $appId = 'Ciceron.Tool.' + $tool.Id
    @{ Name = $tool.Name; AppId = $appId }
    foreach ($alias in $tool.Aliases.GetEnumerator()) {
        @{ Name = $alias.Value; AppId = $appId + '.' + $alias.Key }
    }
}

function Test-CiceronToolShortcut($shell, [string]$path, [string]$id, [string]$destination) {
    if (!(Test-OwnedCiceronToolShortcut $shell $path $id)) { return $false }
    $link = $shell.CreateShortcut($path)
    return $link.TargetPath -eq $destination
}

function Test-OwnedCiceronToolShortcut($shell, [string]$path, [string]$id) {
    $item = Get-Item -LiteralPath $path -ErrorAction SilentlyContinue
    if (!$item -or $item.PSIsContainer -or ($item.Attributes -band [IO.FileAttributes]::ReparsePoint)) { return $false }
    $link = $shell.CreateShortcut($path)
    return ([IO.Path]::GetFileName($link.TargetPath) -ieq 'Ciceron.exe' -and
        $link.Arguments -ceq "--abrir-herramienta $id")
}

function Install-CiceronToolShortcuts($shell, [string]$menu, [string]$destination) {
    $directory = Join-Path $menu 'Ciceron'
    $item = New-Item -Path $directory -ItemType Directory -Force
    if ($item.Attributes -band [IO.FileAttributes]::ReparsePoint) { throw 'La carpeta Ciceron de Inicio apunta a otra ubicación.' }
    if (!('Ciceron.ShellLinkProperties' -as [type])) {
        Add-Type -Path (Join-Path $PSScriptRoot 'propiedades_acceso.cs')
    }
    foreach ($tool in $builtInTools) {
        $registered = $true
        foreach ($entry in Get-CiceronToolShortcuts $tool) {
            if (!(Write-CiceronToolShortcut $shell $directory $destination $tool $entry)) { $registered = $false }
        }
        $oldPath = Join-Path $directory ($tool.OldName + '.lnk')
        if ($registered -and (Test-OwnedCiceronToolShortcut $shell $oldPath $tool.Id)) {
            Remove-Item -LiteralPath $oldPath -Force
        }
    }
}

function Write-CiceronToolShortcut($shell, [string]$directory, [string]$destination, $tool, $entry) {
    $path = Join-Path $directory ($entry.Name + '.lnk')
    $stageLink = Join-Path $directory ('.Ciceron-' + [guid]::NewGuid().ToString('N') + '.lnk')
    try {
        $link = $shell.CreateShortcut($stageLink)
        $link.TargetPath = $destination
        $link.Arguments = '--abrir-herramienta ' + $tool.Id
        $link.WorkingDirectory = Split-Path -Parent $destination
        $link.IconLocation = $destination + ',0'
        $link.Description = 'Cicerón · ' + ($tool.Tags -join ', ')
        $link.Save()
        [Ciceron.ShellLinkProperties]::Set($stageLink, $entry.AppId, [string[]]$tool.Tags)
        if (Test-OwnedCiceronToolShortcut $shell $path $tool.Id) {
            $backupLink = Join-Path $directory ('.Ciceron-respaldo-' + [guid]::NewGuid().ToString('N') + '.lnk')
            [IO.File]::Replace($stageLink, $path, $backupLink, $true)
            if (Test-Path -LiteralPath $backupLink) { Remove-Item -LiteralPath $backupLink -Force }
        } else {
            if (Test-Path -LiteralPath $path) { throw "El acceso «$($entry.Name)» pertenece a otro programa; no se sobrescribió." }
            [IO.File]::Move($stageLink, $path)
        }
        return $true
    } catch {
        Write-Warning "No se pudo preparar el acceso «$($entry.Name)»: $($_.Exception.Message)"
        return $false
    } finally {
        if (Test-Path -LiteralPath $stageLink) { Remove-Item -LiteralPath $stageLink -Force }
    }
}
