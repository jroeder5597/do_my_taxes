"""
Screen reader module for capturing and OCR'ing screen content.
Used for assisting with TaxAct and other tax software.
"""

import tempfile
from pathlib import Path
from typing import Optional

from PIL import Image

from src.utils import get_logger

logger = get_logger(__name__)

# Try to import dependencies
try:
    import mss
    MSS_AVAILABLE = True
except ImportError:
    MSS_AVAILABLE = False
    logger.warning("mss not installed. Screen capture will not be available.")

try:
    import pytesseract
    TESSERACT_AVAILABLE = True
except ImportError:
    TESSERACT_AVAILABLE = False
    logger.warning("pytesseract not installed. Screen OCR will not be available.")


class ScreenReader:
    """
    Capture and OCR screen content for tax software assistance.
    """

    def __init__(self, dpi: int = 150):
        """
        Initialize the screen reader.

        Args:
            dpi: DPI for OCR processing
        """
        if not MSS_AVAILABLE:
            raise RuntimeError("mss is not installed. Install with: pip install mss")

        if not TESSERACT_AVAILABLE:
            raise RuntimeError("pytesseract is not installed. Install with: pip install pytesseract")

        self.dpi = dpi
        self._sct = None

    @property
    def sct(self):
        """Lazy-load MSS screen capture."""
        if self._sct is None:
            self._sct = mss.mss()
        return self._sct

    def get_monitor_info(self) -> list[dict]:
        """
        Get information about available monitors.

        Returns:
            List of monitor info dictionaries
        """
        monitors = []
        for i, monitor in enumerate(self.sct.monitors):
            if i == 0:
                # First entry is all monitors combined
                continue
            monitors.append({
                "index": i,
                "width": monitor["width"],
                "height": monitor["height"],
                "left": monitor["left"],
                "top": monitor["top"],
            })
        return monitors

    def capture_screen(
        self,
        monitor: int = 1,
        region: Optional[tuple[int, int, int, int]] = None,
    ) -> Image.Image:
        """
        Capture the screen or a region.

        Args:
            monitor: Monitor index (1-based)
            region: Optional (left, top, width, height) region to capture

        Returns:
            PIL Image of the captured screen
        """
        if region:
            # Capture specific region
            left, top, width, height = region
            bbox = {
                "left": left,
                "top": top,
                "width": width,
                "height": height,
            }
        else:
            # Capture entire monitor
            bbox = self.sct.monitors[monitor]

        # Capture
        screenshot = self.sct.grab(bbox)

        # Convert to PIL Image
        img = Image.frombytes("RGB", screenshot.size, screenshot.rgb)

        return img

    def ocr_image(self, image: Image.Image) -> str:
        """
        Perform OCR on an image.

        Args:
            image: PIL Image to OCR

        Returns:
            Extracted text
        """
        # Convert to RGB if necessary
        if image.mode != "RGB":
            image = image.convert("RGB")

        # Perform OCR
        text = pytesseract.image_to_string(
            image,
            lang="eng",
            config=f"--dpi {self.dpi}",
        )

        return text.strip()

    def capture_and_ocr(
        self,
        monitor: int = 1,
        region: Optional[tuple[int, int, int, int]] = None,
    ) -> tuple[Image.Image, str]:
        """
        Capture screen and perform OCR.

        Args:
            monitor: Monitor index (1-based)
            region: Optional (left, top, width, height) region to capture

        Returns:
            Tuple of (image, extracted_text)
        """
        image = self.capture_screen(monitor, region)
        text = self.ocr_image(image)
        return image, text

    def save_screenshot(
        self,
        output_path: str | Path,
        monitor: int = 1,
        region: Optional[tuple[int, int, int, int]] = None,
    ) -> Path:
        """
        Save a screenshot to file.

        Args:
            output_path: Path to save the screenshot
            monitor: Monitor index (1-based)
            region: Optional (left, top, width, height) region to capture

        Returns:
            Path to saved file
        """
        image = self.capture_screen(monitor, region)

        path = Path(output_path)
        path.parent.mkdir(parents=True, exist_ok=True)

        image.save(path)
        logger.info(f"Saved screenshot to {path}")

        return path

    def find_text_on_screen(
        self,
        search_text: str,
        monitor: int = 1,
    ) -> Optional[tuple[int, int, int, int]]:
        """
        Find the location of text on screen.

        Args:
            search_text: Text to search for
            monitor: Monitor index (1-based)

        Returns:
            Bounding box (left, top, width, height) or None if not found
        """
        # Capture screen
        image = self.capture_screen(monitor)

        # Get OCR data with bounding boxes
        data = pytesseract.image_to_data(
            image,
            lang="eng",
            output_type=pytesseract.Output.DICT,
        )

        # Search for text
        search_lower = search_text.lower()

        for i, text in enumerate(data.get("text", [])):
            if search_lower in text.lower():
                return (
                    data["left"][i],
                    data["top"][i],
                    data["width"][i],
                    data["height"][i],
                )

        return None

    def get_text_regions(self, image: Image.Image) -> list[dict]:
        """
        Get all text regions from an image with positions.

        Args:
            image: PIL Image to analyze

        Returns:
            List of text regions with text, position, and confidence
        """
        # Convert to RGB if necessary
        if image.mode != "RGB":
            image = image.convert("RGB")

        # Get OCR data
        data = pytesseract.image_to_data(
            image,
            lang="eng",
            output_type=pytesseract.Output.DICT,
        )

        regions = []
        for i, text in enumerate(data.get("text", [])):
            if text.strip():
                regions.append({
                    "text": text,
                    "left": data["left"][i],
                    "top": data["top"][i],
                    "width": data["width"][i],
                    "height": data["height"][i],
                    "confidence": int(data["conf"][i]) if data["conf"][i] != "-1" else 0,
                })

        return regions

    def close(self) -> None:
        """Close the screen capture."""
        if self._sct is not None:
            self._sct.close()
            self._sct = None
