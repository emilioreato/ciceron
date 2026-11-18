function Test-CiceronSourceRunning([string]$Root) {
    $lock = Join-Path $Root 'centro-fuentes.lock'
    if (!(Test-Path -LiteralPath $lock -PathType Leaf)) { return $false }
    try {
        $handle = [IO.File]::Open($lock, 'Open', 'ReadWrite', 'None')
        $handle.Dispose()
        return $false
    } catch [IO.IOException] { return $true }
}

function Stop-CiceronSource([string]$Root) {
    if (!(Test-CiceronSourceRunning $Root)) { return }
    $queue = Join-Path $Root 'datos\arranques-paquetes'
    New-Item -ItemType Directory -Path $queue -Force | Out-Null
    $request = Join-Path $queue ([guid]::NewGuid().ToString('N'))
    [IO.File]::WriteAllText(($request + '.tmp'), '{"control":"quit"}')
    [IO.File]::Move(($request + '.tmp'), ($request + '.json'))
    try {
        for ($attempt = 0; $attempt -lt 100; $attempt++) {
            if (!(Test-CiceronSourceRunning $Root)) { return }
            Start-Sleep -Milliseconds 100
        }
        throw 'Cicerón no respondió al cierre. Ciérralo desde la bandeja y vuelve a intentarlo.'
    } finally {
        if (Test-Path -LiteralPath ($request + '.json')) {
            Remove-Item -LiteralPath ($request + '.json') -ErrorAction SilentlyContinue
        }
    }
}
