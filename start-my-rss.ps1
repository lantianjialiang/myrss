param([switch]$NoBrowser)

$ErrorActionPreference = 'Stop'
$runtime = Join-Path $PSScriptRoot 'runtime'
$null = New-Item -Path $runtime -ItemType Directory -Force

function Test-Health([string]$Url) {
    try { return (Invoke-WebRequest -Uri $Url -TimeoutSec 2 -UseBasicParsing).Content -eq 'ok' }
    catch { return $false }
}

function Start-LocalService([string]$Name, [string]$Executable, [string[]]$ServiceArgs,
                            [string]$Directory, [int]$Port) {
    $health = "http://127.0.0.1:$Port/healthz"
    if (Test-Health $health) { return }
    $process = Start-Process -FilePath $Executable -ArgumentList $ServiceArgs -WorkingDirectory $Directory `
        -RedirectStandardOutput (Join-Path $runtime "$Name.log") `
        -RedirectStandardError (Join-Path $runtime "$Name.err.log") -WindowStyle Hidden -PassThru
    for ($attempt = 0; $attempt -lt 25; $attempt++) {
        if ($process.HasExited) { break }
        if (Test-Health $health) { return }
        Start-Sleep -Milliseconds 400
    }
    throw "$Name failed to start. See $runtime\$Name.err.log"
}

$node = Join-Path $PSScriptRoot 'node24\node.exe'
$hub = Join-Path $PSScriptRoot 'RSSHub'
if (!(Test-Path (Join-Path $hub 'dist\index.mjs'))) {
    throw 'RSSHub dist/index.mjs is missing. Build the existing RSSHub checkout first.'
}
$reader = Join-Path $PSScriptRoot 'reader'
$venv = Join-Path $runtime 'reader-venv'
$python = Join-Path $venv 'Scripts\python.exe'
if (!(Test-Path $python)) {
    & python -m venv $venv
    if ($LASTEXITCODE -ne 0) { throw 'Could not create the reader environment.' }
}
$requirements = Join-Path $reader 'requirements.txt'
$stamp = Join-Path $venv 'requirements.sha256'
$hash = (Get-FileHash -LiteralPath $requirements).Hash
if (!(Test-Path $stamp) -or (Get-Content -LiteralPath $stamp -Raw).Trim() -ne $hash) {
    & $python -m pip install -r $requirements
    if ($LASTEXITCODE -ne 0) { throw 'Could not install the reader dependencies.' }
    Set-Content -LiteralPath $stamp -Value $hash
}

$previousNodeEnv = $env:NODE_ENV
try {
    $env:NODE_ENV = 'production'
    Start-LocalService 'rsshub' $node @('--max-http-header-size=32768', 'dist/index.mjs') $hub 1200
} finally {
    $env:NODE_ENV = $previousNodeEnv
}
Start-LocalService 'reader' $python @('app.py') $reader 1210
Write-Host 'Reader  http://127.0.0.1:1210/'
Write-Host 'RSSHub  http://127.0.0.1:1200/'
if (!$NoBrowser) { Start-Process 'http://127.0.0.1:1210/' }
