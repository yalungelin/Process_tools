from __future__ import annotations

import importlib
import importlib.util
import os
import subprocess
import sys
import types
from pathlib import Path
from typing import Any

_SUBPROCESS_PATCHED = False


class PaddleOCRNotReadyError(RuntimeError):
    """Raised when PaddleOCR or its runtime dependencies are unavailable."""


class PaddleFormulaRecognizer:
    """Lazy wrapper around PaddleOCR FormulaRecognition."""

    def __init__(
        self,
        *,
        paddleocr_repo: str | Path,
        model_name: str = "PP-FormulaNet_plus-S",
        model_dir: str | Path | None = None,
        device: str = "cpu",
    ) -> None:
        self.paddleocr_repo = Path(paddleocr_repo).expanduser().resolve()
        self.model_name = model_name.strip() or "PP-FormulaNet_plus-S"
        self.model_dir = Path(model_dir).expanduser().resolve() if model_dir else None
        self.device = device.strip() if device else "cpu"
        self._model: Any | None = None

    def close(self) -> None:
        if self._model is not None and hasattr(self._model, "close"):
            self._model.close()
        self._model = None

    def predict(self, image_path: str | Path) -> str:
        self._ensure_model()
        assert self._model is not None

        image_path = Path(image_path).resolve()
        try:
            output = self._model.predict(input=str(image_path), batch_size=1)
        except TypeError:
            output = self._model.predict(str(image_path))

        formula = self._extract_formula(output)
        if not formula:
            raise RuntimeError("PaddleOCR did not return a rec_formula field.")
        return formula

    def _ensure_model(self) -> None:
        if self._model is not None:
            return

        self._configure_runtime_cache()
        self._patch_subprocess_no_window()
        self._install_optional_download_stubs()

        try:
            FormulaRecognition = self._load_formula_recognition_class()
        except Exception as exc:  # pragma: no cover - depends on local runtime
            raise PaddleOCRNotReadyError(
                "Cannot import PaddleOCR FormulaRecognition. Install PaddleOCR "
                "dependencies in the current conda environment first."
            ) from exc

        self._validate_device()

        kwargs: dict[str, Any] = {"model_name": self.model_name}
        model_dir = self.model_dir or self._cached_model_dir()
        if model_dir:
            kwargs["model_dir"] = str(model_dir)
        if self.device and self.device.lower() != "auto":
            kwargs["device"] = self.device
        if self.device.lower().startswith("cpu"):
            kwargs.update(
                {
                    "engine": "paddle",
                    "enable_mkldnn": True,
                    "mkldnn_cache_capacity": 20,
                    "cpu_threads": self._cpu_threads(),
                }
            )

        try:
            self._model = FormulaRecognition(**kwargs)
        except Exception as exc:  # pragma: no cover - depends on local runtime
            raise PaddleOCRNotReadyError(
                "Failed to create PaddleOCR FormulaRecognition model. "
                "Check paddlepaddle/paddlex installation, model name, device, "
                "and local model directory."
            ) from exc

    def _configure_runtime_cache(self) -> None:
        if getattr(sys, "frozen", False):
            cache_root = Path(sys.executable).resolve().parent / "cache" / "runtime"
        else:
            cache_root = Path(__file__).resolve().parent / ".cache" / "runtime"
        cache_root.mkdir(parents=True, exist_ok=True)

        os.environ["PADDLE_PDX_MODEL_SOURCE"] = "BOS"
        os.environ["PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK"] = "True"
        os.environ["PADDLE_PDX_CACHE_HOME"] = str(cache_root / "paddlex")
        os.environ.setdefault("PADDLE_HOME", str(cache_root / "paddle"))
        os.environ.setdefault(
            "PADDLE_EXTENSION_DIR", str(cache_root / "paddle_extension")
        )

        # Paddle still has a few legacy paths under expanduser("~/.cache").
        # For this self-contained tool, keep those files inside the workspace.
        if os.environ.get("FORMULA_OCR_USE_LOCAL_CACHE", "1") != "0":
            os.environ.setdefault("HOME", str(cache_root / "home"))
            os.environ.setdefault("USERPROFILE", str(cache_root / "home"))

    def _cached_model_dir(self) -> Path | None:
        cache_home = os.environ.get("PADDLE_PDX_CACHE_HOME")
        if not cache_home:
            return None
        model_dir = Path(cache_home) / "official_models" / self.model_name
        has_inference_model = (
            (model_dir / "inference.json").exists()
            and (model_dir / "inference.yml").exists()
        )
        if has_inference_model:
            return model_dir

        if getattr(sys, "frozen", False):
            raise PaddleOCRNotReadyError(
                f"Local model files were not found for {self.model_name}: {model_dir}. "
                "This offline build only includes cached models. Use the bundled "
                "PP-FormulaNet_plus-S model or place the model directory manually."
            )
        return None

    def _validate_device(self) -> None:
        if not self.device.lower().startswith("gpu"):
            return
        try:
            import paddle
        except Exception as exc:
            raise PaddleOCRNotReadyError("Cannot import paddle to check GPU support.") from exc

        if not paddle.device.is_compiled_with_cuda():
            raise PaddleOCRNotReadyError(
                "The current Paddle runtime is CPU-only. Select device `cpu`, "
                "or rebuild this app with paddlepaddle-gpu."
            )
        try:
            if paddle.device.cuda.device_count() < 1:
                raise PaddleOCRNotReadyError("No CUDA GPU is visible to Paddle.")
        except AttributeError as exc:
            raise PaddleOCRNotReadyError("Paddle CUDA device query is unavailable.") from exc

    def _load_formula_recognition_class(self) -> type:
        package_dir = self._paddleocr_package_dir()
        self._install_minimal_paddleocr_package(package_dir)
        module = importlib.import_module("paddleocr._models.formula_recognition")
        return module.FormulaRecognition

    def _paddleocr_package_dir(self) -> Path:
        local_package = self.paddleocr_repo / "paddleocr"
        if local_package.exists():
            return local_package

        if self.paddleocr_repo.name == "paddleocr" and self.paddleocr_repo.exists():
            return self.paddleocr_repo

        spec = importlib.util.find_spec("paddleocr")
        if spec and spec.submodule_search_locations:
            return Path(next(iter(spec.submodule_search_locations))).resolve()

        if not self.paddleocr_repo.exists():
            raise PaddleOCRNotReadyError(
                f"PaddleOCR repo was not found: {self.paddleocr_repo}"
            )

        raise PaddleOCRNotReadyError(
            f"Invalid PaddleOCR repo, missing package: {local_package}"
        )

    def _install_minimal_paddleocr_package(self, package_dir: Path) -> None:
        package_parent = str(package_dir.parent)
        if package_parent in sys.path:
            sys.path.remove(package_parent)
        sys.path.insert(0, package_parent)

        for name in list(sys.modules):
            if name == "paddleocr" or name.startswith("paddleocr."):
                del sys.modules[name]

        package = types.ModuleType("paddleocr")
        package.__file__ = str(package_dir / "__init__.py")
        package.__path__ = [str(package_dir)]  # type: ignore[attr-defined]
        package.__package__ = "paddleocr"
        sys.modules["paddleocr"] = package

        models_package = types.ModuleType("paddleocr._models")
        models_package.__file__ = str(package_dir / "_models" / "__init__.py")
        models_package.__path__ = [str(package_dir / "_models")]  # type: ignore[attr-defined]
        models_package.__package__ = "paddleocr._models"
        sys.modules["paddleocr._models"] = models_package

    def _install_optional_download_stubs(self) -> None:
        if not getattr(sys, "frozen", False):
            return
        if "modelscope" not in sys.modules:
            module = types.ModuleType("modelscope")
            module.__doc__ = "Offline FormulaOCR stub for PaddleX model source imports."
            sys.modules["modelscope"] = module

    @staticmethod
    def _patch_subprocess_no_window() -> None:
        global _SUBPROCESS_PATCHED
        if _SUBPROCESS_PATCHED or os.name != "nt":
            return

        original_popen = subprocess.Popen
        create_no_window = getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)
        startupinfo_flag = getattr(subprocess, "STARTF_USESHOWWINDOW", 1)

        class QuietPopen(original_popen):  # type: ignore[misc, valid-type]
            def __init__(self, *args, **kwargs):
                kwargs["creationflags"] = (
                    kwargs.get("creationflags", 0) | create_no_window
                )
                startupinfo = kwargs.get("startupinfo")
                if startupinfo is None:
                    startupinfo = subprocess.STARTUPINFO()
                startupinfo.dwFlags |= startupinfo_flag
                startupinfo.wShowWindow = 0
                kwargs["startupinfo"] = startupinfo
                super().__init__(*args, **kwargs)

        subprocess.Popen = QuietPopen  # type: ignore[assignment]
        _SUBPROCESS_PATCHED = True

    @staticmethod
    def _cpu_threads() -> int:
        raw_value = os.environ.get("FORMULA_OCR_CPU_THREADS", "").strip()
        if raw_value.isdigit():
            return max(1, int(raw_value))
        return max(2, min(os.cpu_count() or 4, 10))

    @staticmethod
    def _extract_formula(output: Any) -> str:
        for item in output or []:
            formula = PaddleFormulaRecognizer._read_formula_field(item)
            if formula:
                return formula.strip()
        return ""

    @staticmethod
    def _read_formula_field(item: Any) -> str:
        if hasattr(item, "get"):
            value = item.get("rec_formula")
            if value:
                return str(value)
            nested = item.get("res")
            if hasattr(nested, "get"):
                value = nested.get("rec_formula")
                if value:
                    return str(value)

        if hasattr(item, "to_dict"):
            data = item.to_dict()
            if isinstance(data, dict):
                return PaddleFormulaRecognizer._read_formula_field(data)

        if hasattr(item, "json"):
            data = item.json()
            if isinstance(data, dict):
                return PaddleFormulaRecognizer._read_formula_field(data)

        return ""
