# Third-Party Notices

FormulaOCR depends on open-source OCR and formula-recognition components. This file records the main third-party projects used by the application and the notices users should keep when redistributing binaries or offline model packages.

## PaddleOCR

- Project: PaddleOCR
- Repository: https://github.com/PaddlePaddle/PaddleOCR
- Organization: PaddlePaddle / PaddleOCR Authors
- License: Apache License 2.0
- Use in this project: formula recognition through PaddleOCR/PaddleX formula-recognition models.

PaddleOCR source code and model files are not vendored in this repository. If you redistribute a packaged build that includes PaddleOCR, PaddlePaddle, PaddleX, runtime libraries, or model weights, keep the original third-party license files, copyright notices, and any model-specific usage terms with the distributed package.

Suggested citation or acknowledgement:

```text
This software uses PaddleOCR, an open-source OCR toolkit from the PaddlePaddle ecosystem:
https://github.com/PaddlePaddle/PaddleOCR
```

## Python Libraries

The application also uses Python packages listed in `requirements.txt`, including Pillow, paddlepaddle, paddlex, latex2mathml, requests, aiohttp, tokenizers, ftfy, and PyInstaller. Their licenses are controlled by their respective upstream projects.
