# Regenerates OCOBot.lnk - a no-console shortcut that opens the OCOBot GUI (G1.16 / G-LAUNCH-01).
# Target: pythonw.exe -m ocobot.ui.app ; WorkingDirectory: project root ; no console window.
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$pythonw = $null
$cmd = Get-Command pythonw.exe -ErrorAction SilentlyContinue
if ($cmd) { $pythonw = $cmd.Source }
if (-not $pythonw) {
    $py = Get-Command python.exe -ErrorAction SilentlyContinue
    if ($py) {
        $cand = Join-Path (Split-Path -Parent $py.Source) 'pythonw.exe'
        if (Test-Path $cand) { $pythonw = $cand }
    }
}
if (-not $pythonw) { throw 'pythonw.exe not found on PATH. Install Python 3.10+ and add it to PATH.' }
$lnk = Join-Path $root 'OCOBot.lnk'
$ws = New-Object -ComObject WScript.Shell
$sc = $ws.CreateShortcut($lnk)
$sc.TargetPath = $pythonw
$sc.Arguments = '-m ocobot.ui.app'
$sc.WorkingDirectory = $root
$sc.IconLocation = $pythonw
$sc.Description = 'OCOBot GUI (Testnet) - no console'
$sc.Save()
Write-Output ("Created: {0} -> {1} -m ocobot.ui.app (WorkingDirectory={2})" -f $lnk, $pythonw, $root)
