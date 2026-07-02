$ErrorActionPreference = "Stop"

$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$envRoot = "C:\D\anaconda3\envs\formula_ocr"
$python = Join-Path $envRoot "python.exe"
$pyinstaller = Join-Path $envRoot "Scripts\pyinstaller.exe"
$iconSvg = Join-Path $root "icon.svg"
$iconPng = Join-Path $root "icon.png"
$iconIco = Join-Path $root "icon.ico"

if (-not (Test-Path $python)) {
    throw "Python not found: $python"
}
if (-not (Test-Path $pyinstaller)) {
    & $python -m pip install pyinstaller
}

Set-Location $root
$env:PATH = (Join-Path $envRoot "Library\bin") + ";" + $env:PATH

function Find-Browser {
    $candidates = @(
        (Join-Path ${env:ProgramFiles(x86)} "Microsoft\Edge\Application\msedge.exe"),
        (Join-Path $env:ProgramFiles "Google\Chrome\Application\chrome.exe")
    )
    foreach ($candidate in $candidates) {
        if ($candidate -and (Test-Path $candidate)) {
            return $candidate
        }
    }
    return $null
}

function Update-IconAssets {
    if (-not (Test-Path $iconSvg)) {
        return
    }

    $needsUpdate = $true
    if ((Test-Path $iconPng) -and (Test-Path $iconIco)) {
        $svgTime = (Get-Item $iconSvg).LastWriteTimeUtc
        $pngTime = (Get-Item $iconPng).LastWriteTimeUtc
        $icoTime = (Get-Item $iconIco).LastWriteTimeUtc
        $needsUpdate = ($pngTime -lt $svgTime) -or ($icoTime -lt $svgTime)
    }
    if (-not $needsUpdate) {
        return
    }

    $browser = Find-Browser
    if (-not $browser) {
        Write-Warning "Cannot render icon.svg because Edge/Chrome was not found."
        return
    }

    New-Item -ItemType Directory -Force -Path (Join-Path $root "build") | Out-Null
    $renderHtml = Join-Path $root "build\icon_render.html"
    $svg = Get-Content -LiteralPath $iconSvg -Raw -Encoding UTF8
    $html = @"
<!doctype html>
<html>
<head>
<meta charset="utf-8">
<style>
html,body{margin:0;width:512px;height:512px;background:transparent;overflow:hidden}
svg{display:block;width:512px;height:512px}
</style>
</head>
<body>$svg</body>
</html>
"@
    Set-Content -LiteralPath $renderHtml -Value $html -Encoding UTF8
    $renderUri = [System.Uri]::new($renderHtml).AbsoluteUri
    & $browser `
        --headless `
        --disable-gpu `
        --hide-scrollbars `
        --default-background-color=00000000 `
        --window-size=512,512 `
        "--screenshot=$iconPng" `
        $renderUri | Out-Null

    & $python -c "from PIL import Image; img=Image.open(r'$iconPng').convert('RGBA'); img.save(r'$iconIco', sizes=[(256,256),(128,128),(64,64),(48,48),(32,32),(16,16)])"
}

Update-IconAssets

$pyinstallerArgs = @(
    "--noconfirm",
    "--clean",
    "--onedir",
    "--windowed",
    "--name", "FormulaOCR",
    "--contents-directory", "_internal",
    "--add-data", "$root\PaddleOCR-main\paddleocr;PaddleOCR-main\paddleocr",
    "--collect-all", "paddle",
    "--collect-all", "paddlex",
    "--collect-all", "cv2",
    "--collect-all", "tokenizers",
    "--collect-all", "pypdfium2",
    "--collect-all", "latex2mathml",
    "--copy-metadata", "tokenizers",
    "--copy-metadata", "latex2mathml",
    "--hidden-import", "paddle",
    "--hidden-import", "paddlex",
    "--hidden-import", "tokenizers"
)

if (Test-Path $iconIco) {
    $pyinstallerArgs += @("--icon", $iconIco)
}
if (Test-Path $iconPng) {
    $pyinstallerArgs += @("--add-data", "$iconPng;.")
}
if (Test-Path $iconIco) {
    $pyinstallerArgs += @("--add-data", "$iconIco;.")
}

$excludeModules = @(
    "tensorflow",
    "torch",
    "torchvision",
    "torchaudio",
    "modelscope",
    "matplotlib",
    "sklearn",
    "scipy",
    "paddle.tensorrt",
    "paddlex.inference.serving",
    "shapely.tests"
)
foreach ($module in $excludeModules) {
    $pyinstallerArgs += @("--exclude-module", $module)
}

$pyinstallerArgs += "$root\formula_ocr_app\app.py"

& $pyinstaller @pyinstallerArgs
if ($LASTEXITCODE -ne 0) {
    throw "PyInstaller failed with exit code $LASTEXITCODE"
}

$internalDir = Join-Path $root "dist\FormulaOCR\_internal"
Copy-Item -Force (Join-Path $envRoot "Library\bin\tcl86t.dll") (Join-Path $internalDir "tcl86t.dll")
Copy-Item -Force (Join-Path $envRoot "Library\bin\tk86t.dll") (Join-Path $internalDir "tk86t.dll")
Copy-Item -Force (Join-Path $envRoot "Library\bin\expat.dll") (Join-Path $internalDir "expat.dll")
Copy-Item -Force (Join-Path $envRoot "Library\bin\libexpat.dll") (Join-Path $internalDir "libexpat.dll")

$srcModelsRoot = Join-Path $root "formula_ocr_app\.cache\runtime\paddlex\official_models"
$dstModelsRoot = Join-Path $root "dist\FormulaOCR\cache\runtime\paddlex\official_models"
if (Test-Path $srcModelsRoot) {
    New-Item -ItemType Directory -Force -Path $dstModelsRoot | Out-Null
    Get-ChildItem -LiteralPath $srcModelsRoot -Directory | ForEach-Object {
        Copy-Item -LiteralPath $_.FullName -Destination (Join-Path $dstModelsRoot $_.Name) -Recurse -Force
    }
}

Write-Host "Built: $root\dist\FormulaOCR\FormulaOCR.exe"
