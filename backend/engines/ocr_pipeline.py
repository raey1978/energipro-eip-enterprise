"""
EIP v6.3C — OCR Pipeline with Provider Abstraction

Architecture:
  OcrProvider (abstract) ← TesseractProvider (default)
                         ← AzureOcrProvider  (future stub)
                         ← AwsTextractProvider (future stub)

Usage:
  provider = get_ocr_provider()
  result = provider.ocr_page(image: PIL.Image) -> OcrResult

Failure contract:
  - If no provider available: raise OcrNotAvailable with actionable message
  - Never silently return empty string from a readable image
  - All providers log processing time and confidence
"""
from __future__ import annotations
import time, logging, re
from dataclasses import dataclass, field
from typing import Optional
from abc import ABC, abstractmethod
from PIL import Image

logger = logging.getLogger("eip.ocr")


@dataclass
class OcrResult:
    text:           str
    confidence:     float         # 0.0 - 1.0
    word_count:     int
    char_count:     int
    method:         str           # tesseract | azure | aws | none
    processing_ms:  float
    warnings:       list[str] = field(default_factory=list)
    page_quality:   str = "unknown"  # good | acceptable | low | failed


class OcrNotAvailable(Exception):
    """Raised when no OCR provider is configured or available."""
    pass


class OcrProvider(ABC):
    """Abstract base class for OCR providers."""
    @property
    @abstractmethod
    def name(self) -> str: ...

    @abstractmethod
    def is_available(self) -> bool: ...

    @abstractmethod
    def ocr_page(self, image: Image.Image, lang: str = "eng") -> OcrResult: ...


class TesseractProvider(OcrProvider):
    """
    Default OCR provider using local Tesseract 5.x.
    Requires: tesseract binary + pytesseract Python package.
    """
    @property
    def name(self) -> str: return "tesseract"

    def is_available(self) -> bool:
        try:
            import pytesseract
            pytesseract.get_tesseract_version()
            return True
        except Exception:
            return False

    def ocr_page(self, image: Image.Image, lang: str = "eng") -> OcrResult:
        import pytesseract
        t0 = time.perf_counter()
        warnings = []

        # Pre-process image for better OCR accuracy
        img = self._preprocess(image, warnings)

        # Run Tesseract — get text + confidence
        try:
            data = pytesseract.image_to_data(
                img, lang=lang, config="--psm 6",
                output_type=pytesseract.Output.DICT
            )
            # Collect words above confidence threshold
            words    = []
            conf_sum = 0.0
            conf_n   = 0
            for i, word in enumerate(data["text"]):
                conf = int(data["conf"][i])
                if conf > 0 and word.strip():
                    words.append(word)
                    conf_sum += conf
                    conf_n   += 1

            text = " ".join(words)
            avg_conf = (conf_sum / max(conf_n, 1)) / 100.0

        except Exception as e:
            warnings.append(f"Tesseract error: {str(e)[:80]}")
            text     = ""
            avg_conf = 0.0

        ms = round((time.perf_counter() - t0) * 1000, 1)

        wc = len(text.split()) if text else 0
        cc = len(text)

        quality = (
            "good"       if avg_conf >= 0.75 and wc >= 10 else
            "acceptable" if avg_conf >= 0.50 and wc >= 3  else
            "low"        if wc > 0 else
            "failed"
        )

        if avg_conf < 0.50 and wc > 0:
            warnings.append(f"Low OCR confidence: {avg_conf:.0%}")
        if wc == 0:
            warnings.append("OCR returned zero words from this page")

        return OcrResult(
            text=text, confidence=avg_conf, word_count=wc,
            char_count=cc, method="tesseract",
            processing_ms=ms, warnings=warnings, page_quality=quality
        )

    def _preprocess(self, image: Image.Image, warnings: list) -> Image.Image:
        """Greyscale + mild contrast boost — improves OCR accuracy on field scans."""
        try:
            img = image.convert("L")              # greyscale
            from PIL import ImageEnhance
            img = ImageEnhance.Contrast(img).enhance(1.5)
            return img
        except Exception as e:
            warnings.append(f"Image preprocessing skipped: {e}")
            return image


class AzureOcrProvider(OcrProvider):
    """Future stub — Azure Document Intelligence. Not implemented."""
    @property
    def name(self) -> str: return "azure"

    def is_available(self) -> bool:
        import os
        return bool(os.environ.get("AZURE_OCR_KEY") and os.environ.get("AZURE_OCR_ENDPOINT"))

    def ocr_page(self, image: Image.Image, lang: str = "eng") -> OcrResult:
        raise NotImplementedError(
            "Azure OCR provider is not yet implemented. "
            "Set AZURE_OCR_KEY and AZURE_OCR_ENDPOINT and implement this class."
        )


def get_ocr_provider(preferred: str = "tesseract") -> OcrProvider:
    """
    Return the best available OCR provider.
    Raises OcrNotAvailable if nothing is configured.
    """
    providers = {
        "tesseract": TesseractProvider(),
        "azure":     AzureOcrProvider(),
    }
    # Try preferred first
    p = providers.get(preferred)
    if p and p.is_available():
        return p
    # Fallback chain
    for name, provider in providers.items():
        if provider.is_available():
            logger.info("OCR provider fallback: using %s", name)
            return provider
    raise OcrNotAvailable(
        "No OCR provider is available. "
        "Install tesseract: 'apt install tesseract-ocr' and 'pip install pytesseract pdf2image'. "
        "Alternatively configure AZURE_OCR_KEY for cloud OCR."
    )
