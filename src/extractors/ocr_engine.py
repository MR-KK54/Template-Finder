import io
import os
from typing import Optional, List
from src.utils.logger import get_logger

logger = get_logger("ocr_engine")

TESSERACT_CANDIDATE_PATHS = [
    r"C:\Program Files\Tesseract-OCR\tesseract.exe",
    r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe",
    os.path.expandvars(r"%LOCALAPPDATA%\Programs\Tesseract-OCR\tesseract.exe"),
    os.path.expandvars(r"%LOCALAPPDATA%\Tesseract-OCR\tesseract.exe"),
]

class OCREngine:
    """OCR Engine with RapidOCR (ONNX, no system binary) as primary and
    Tesseract/pytesseract as fallback. Enables scanned PDF support."""

    def __init__(self):
        self._rapid_ocr = None
        self._tesseract = None
        self._init_ocr()

    def _find_tesseract(self) -> Optional[str]:
        for path in TESSERACT_CANDIDATE_PATHS:
            if os.path.exists(path):
                return path
        return None

    def _init_ocr(self):
        """Initializes RapidOCR (primary) and pytesseract (fallback)."""
        try:
            from rapidocr_onnxruntime import RapidOCR
            self._rapid_ocr = RapidOCR()
            logger.info("RapidOCR (ONNX) initialized as primary OCR engine.")
        except Exception as e:
            logger.warning(f"RapidOCR unavailable ({e}). Trying Tesseract fallback.")

        if self._rapid_ocr is None:
            try:
                import pytesseract
                tess_path = self._find_tesseract()
                if tess_path:
                    pytesseract.pytesseract.tesseract_cmd = tess_path
                    self._tesseract = pytesseract
                    logger.info(f"PyTesseract initialized as fallback OCR engine ({tess_path}).")
                else:
                    logger.warning("Tesseract binary not found on system - scanned PDFs will not produce text.")
            except Exception as e:
                logger.warning(f"PyTesseract not available: {e}")

    def is_available(self) -> bool:
        return self._rapid_ocr is not None or self._tesseract is not None

    def perform_ocr_on_image(self, image_bytes: bytes) -> str:
        """Extracts text from raw image bytes preserving reading order."""
        if not image_bytes:
            return ""

        # 1. Primary: RapidOCR (ONNX, multilingual incl. Chinese + English)
        if self._rapid_ocr:
            try:
                import numpy as np
                from PIL import Image
                img = Image.open(io.BytesIO(image_bytes)).convert("RGB")
                img_np = np.array(img)
                result, _ = self._rapid_ocr(img_np)
                if result:
                    lines = []
                    for item in result:
                        text_box = item[1] if isinstance(item, (list, tuple)) and len(item) > 1 else ""
                        if isinstance(text_box, str) and text_box.strip():
                            lines.append(text_box.strip())
                    return "\n".join(lines)
                return ""
            except Exception as e:
                logger.error(f"RapidOCR processing error: {e}")

        # 2. Fallback: PyTesseract
        if self._tesseract:
            try:
                from PIL import Image
                img = Image.open(io.BytesIO(image_bytes))
                text = self._tesseract.image_to_string(img)
                return text.strip()
            except Exception as e:
                logger.error(f"PyTesseract processing error: {e}")

        logger.warning("No OCR library available to process scanned image.")
        return ""