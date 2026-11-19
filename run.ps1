param(
    [switch]$Push,
    [switch]$NoLLM,
    [switch]$Open,
    [int]$Timeout = 15
)

$ErrorActionPreference = "Stop"
$project = $PSScriptRoot

# 优先使用 DSH 自带的 Python；换电脑时自动回退到系统 python。
$bundled = "C:\Users\ASUS\.dsh\dsh-runtimes\dsh-primary-runtime\dependencies\python\python.exe"
$python = if (Test-Path $bundled) { $bundled } else { "python" }

$runArgs = @("run.py", "--timeout", "$Timeout")
if ($NoLLM) { $runArgs += "--no-llm" }
if ($Push) { $runArgs += "--push" }

Push-Location $project
try {
    & $python @runArgs
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
    if ($Open) {
        Start-Process (Join-Path $project "output\latest.html")
    }
}
finally {
    Pop-Location
}
