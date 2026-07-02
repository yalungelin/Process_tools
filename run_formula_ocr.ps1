$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $root
$envPython = "C:\D\anaconda3\envs\formula_ocr\python.exe"
if (Test-Path $envPython) {
    & $envPython -m formula_ocr_app.app
} else {
    python -m formula_ocr_app.app
}
