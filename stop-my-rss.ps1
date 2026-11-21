param([switch]$HubOnly)

$ErrorActionPreference = 'Stop'
$node = Join-Path $PSScriptRoot 'node24\node.exe'
$readerPython = Join-Path $PSScriptRoot 'runtime\reader-venv\Scripts\python.exe'

function Stop-LocalService([string]$Name, [int]$Port, [scriptblock]$IsExpectedProcess) {
    $listeners = Get-NetTCPConnection -State Listen -ErrorAction Stop |
        Where-Object { $_.LocalAddress -eq '127.0.0.1' -and $_.LocalPort -eq $Port }
    if (!$listeners) {
        Write-Host "$Name is already stopped."
        return
    }

    foreach ($processId in ($listeners.OwningProcess | Select-Object -Unique)) {
        $process = Get-CimInstance Win32_Process -Filter "ProcessId = $processId"
        if (!$process) { continue }
        if (!(& $IsExpectedProcess $process)) {
            throw "Port $Port belongs to a different process (PID $processId)."
        }
        $running = Get-Process -Id $processId -ErrorAction SilentlyContinue
        if ($running -and [Math]::Abs(($running.StartTime - $process.CreationDate).TotalMilliseconds) -lt 1) {
            Stop-Process -InputObject $running
            $null = $running.WaitForExit(5000)
        }
    }
    if (Get-NetTCPConnection -State Listen -ErrorAction Stop |
        Where-Object { $_.LocalAddress -eq '127.0.0.1' -and $_.LocalPort -eq $Port }) {
        throw "$Name is still listening on port $Port."
    }
    Write-Host "$Name stopped."
}

$failed = $false
if (!$HubOnly) {
    try {
        Stop-LocalService 'Reader' 1210 {
            param($process)
            if ($process.Name -ne 'python.exe' -or $process.CommandLine -notmatch '\s+"?app\.py"?\s*$') {
                return $false
            }
            if ($process.ExecutablePath -eq $readerPython) { return $true }
            $parent = Get-CimInstance Win32_Process -Filter "ProcessId = $($process.ParentProcessId)"
            return ($parent.ExecutablePath -eq $readerPython -and $parent.CreationDate -le $process.CreationDate)
        }
    } catch {
        Write-Warning $_.Exception.Message
        $failed = $true
    }
}
try {
    Stop-LocalService 'RSSHub' 1200 {
        param($process)
        return ($process.ExecutablePath -eq $node -and $process.CommandLine -match '\s+"?dist[\\/]index\.mjs"?\s*$')
    }
} catch {
    Write-Warning $_.Exception.Message
    $failed = $true
}
if ($failed) { exit 1 }
