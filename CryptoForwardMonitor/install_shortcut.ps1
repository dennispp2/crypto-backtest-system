$ErrorActionPreference = 'Stop'
$appDir = $PSScriptRoot
$desktop = [Environment]::GetFolderPath('Desktop')
$shortcutPath = Join-Path $desktop 'Crypto Forward Monitor.lnk'
$exePath = Join-Path $appDir 'dist\CryptoForwardMonitor.exe'
$pythonwPath = [System.IO.Path]::GetFullPath((Join-Path $appDir '..\.venv\Scripts\pythonw.exe'))
$appPath = Join-Path $appDir 'app.py'

$shell = New-Object -ComObject WScript.Shell
$shortcut = $shell.CreateShortcut($shortcutPath)
if (Test-Path -LiteralPath $exePath) {
    $shortcut.TargetPath = $exePath
    $shortcut.Arguments = ''
    $shortcut.WorkingDirectory = (Split-Path -Parent $exePath)
    $shortcut.IconLocation = "$exePath,0"
} else {
    if (-not (Test-Path -LiteralPath $pythonwPath)) {
        throw "pythonw.exe not found: $pythonwPath"
    }
    $shortcut.TargetPath = $pythonwPath
    $shortcut.Arguments = '"' + $appPath + '"'
    $shortcut.WorkingDirectory = $appDir
    $shortcut.IconLocation = "$pythonwPath,0"
}
$shortcut.Description = '凍結版 V3.10 前瞻紙上測試監控程式'
$shortcut.Save()
Write-Output "Created: $shortcutPath"
