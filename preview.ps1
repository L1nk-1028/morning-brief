param([int]$Port = 8765)

$ErrorActionPreference = "Stop"
$project = $PSScriptRoot
$bundled = "C:\Users\ASUS\.dsh\dsh-runtimes\dsh-primary-runtime\dependencies\python\python.exe"
$python = if (Test-Path $bundled) { $bundled } else { "python" }

Write-Host "电脑上打开：http://127.0.0.1:$Port/"
Write-Host "手机上打开：http://<这台电脑的局域网IP>:$Port/  （手机和电脑要连同一个 Wi-Fi）"
Write-Host "按 Ctrl+C 停止。"

& $python -m http.server $Port --bind 0.0.0.0 --directory (Join-Path $project "docs")
