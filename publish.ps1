param(
    [string]$Repo = "morning-brief"
)

$ErrorActionPreference = "Stop"
$project = $PSScriptRoot
$bundled = "C:\Users\ASUS\.dsh\dsh-runtimes\dsh-primary-runtime\dependencies\python\python.exe"
$python = if (Test-Path $bundled) { $bundled } else { "python" }

Write-Host "这个脚本会把 morning-brief 上传到你的 GitHub 仓库。"
Write-Host "你需要先在 GitHub 创建一个 classic token（勾选 repo 和 workflow）。"
Write-Host "Token 输入时不会显示，也不会保存到文件。"
Write-Host ""

Push-Location $project
try {
    & $python publish_github.py --repo $Repo
    exit $LASTEXITCODE
}
finally {
    Pop-Location
}
