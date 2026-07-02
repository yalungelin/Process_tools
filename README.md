# FormulaOCR

FormulaOCR 是一个本地运行的公式识别小工具。它使用 PaddleOCR 的公式识别模型，将图片、剪贴板图片或截图中的数学公式识别为 LaTeX，并提供 MathML、AsciiMath、Typst、Word 线性公式和 DOCX 导出能力。

## 功能

- 打开本地公式图片、粘贴剪贴板图片或框选截图。
- 使用 `PP-FormulaNet_plus-S/M/L` 三档模型识别公式。
- 自动清理识别出的 LaTeX，并复制到剪贴板。
- 将 LaTeX 转换为 MathML、AsciiMath、Typst 和 Word 线性公式。
- 为 Word 优化 MathML 粘贴格式，支持一键复制到剪贴板。
- 生成 MathML 预览图，并可导出包含公式结果的 DOCX 文件。
- 提供 Windows 桌面 GUI 和 PyInstaller 打包脚本。

## 项目结构

```text
formula_ocr_app/
  app.py                  # Tkinter 桌面界面和应用入口
  recognizer.py           # PaddleOCR 公式识别封装
  formula_formats.py      # LaTeX/MathML/AsciiMath/Typst/Word 格式转换
  word_clipboard.py       # Word 兼容剪贴板写入
  word_clipboard_tests.py # Word MathML 回归测试
  word_paste_tests.py     # Word 粘贴相关测试
build_exe.ps1             # Windows 打包脚本
run_formula_ocr.ps1       # Windows 启动脚本
requirements.txt          # Python 依赖
icon.svg / icon.png / icon.ico
```

`dist/`、`build/`、缓存、日志、临时 Word/MathML 转换验证目录以及第三方 PaddleOCR 源码目录不纳入仓库。

## 环境

建议使用 Python 3.10。Windows 下可以使用 Conda：

```powershell
conda create -n formula_ocr python=3.10 pip -y
conda activate formula_ocr
python -m pip install -r requirements.txt
```

如果 `paddlepaddle` 默认源安装失败，可以按 Paddle 官方 CPU 轮子源安装：

```powershell
python -m pip install paddlepaddle==3.2.0 -i https://www.paddlepaddle.org.cn/packages/stable/cpu/
python -m pip install "paddlex[ocr-core]>=3.6.0,<3.7.0" PyYAML requests aiohttp tokenizers ftfy latex2mathml pillow
```

## 运行

```powershell
python -m formula_ocr_app.app
```

或者在 Windows 上运行：

```powershell
.\run_formula_ocr.ps1
```

首次使用模型时，PaddleOCR/PaddleX 可能需要下载模型文件。打包后的离线版本可以把模型缓存放入 `dist/FormulaOCR/cache/runtime/paddlex/official_models`。

## 使用

1. 打开程序。
2. 点击打开图片、粘贴图片或截图。
3. 选择模型等级。
4. 点击识别。
5. 在右侧查看 LaTeX 和格式转换结果。
6. 按需复制 LaTeX、复制 Word MathML、复制其他格式或导出 DOCX。

## 打包

Windows 下可使用 PyInstaller 打包：

```powershell
.\build_exe.ps1
```

脚本默认查找 `C:\D\anaconda3\envs\formula_ocr` 环境。如果你的 Conda 安装路径不同，需要先调整脚本中的 `$envRoot`，或者直接参考脚本里的 PyInstaller 参数执行。

打包产物会输出到：

```text
dist/FormulaOCR/
```

上传到 GitHub 时不要提交 `dist/` 和 `build/`，它们体积很大且可以重新生成。

## 测试

```powershell
python -m formula_ocr_app.app --word-mathml-self-test
python -m formula_ocr_app.app --clipboard-self-test
python -m formula_ocr_app.app --preview-self-test
```

部分测试依赖 Windows 剪贴板、Word 兼容格式或本地浏览器。

## 说明

本仓库只保存应用逻辑、界面代码、格式转换代码和必要资源。模型文件、PaddleOCR 第三方源码、打包后的可执行文件、日志和临时转换验证文件应通过 `.gitignore` 排除。
