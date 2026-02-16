"""
Screen reader module for capturing and OCR'ing screen content.
Used for assisting with TaxAct and other tax software.
Uses Ollama Vision for OCR instead of Tesseract.
"""

from pathlib import Path
from typing import Optional

from PIL import Image

from src.utils import get_logger
from src.utils.config import get_settings

logger = get_logger(__name__)

# Try to import dependencies
try:
    import mss
    MSS_AVAILABLE = True
except ImportError:
    MSS_AVAILABLE = False
    logger.warning("mss not installed. Screen capture will not be available.")


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
        
        self.dpi = dpi
        self._sct = None
        self._ocr = None
    
    @property
    def sct(self):
        """Lazy-load MSS screen capture."""
        if self._sct is None:
            self._sct = mss.mss()
        return self._sct
    
    def _get_ocr(self):
        """Lazy-load Ollama Vision OCR."""
        if self._ocr is None:
            from src.ocr.ollama_vision_ocr import OllamaVisionOCR
            settings = get_settings()
            self._ocr = OllamaVisionOCR(
                model=settings.ocr.ollama_vision.model,
                base_url=settings.llm.ollama.base_url,
                temperature=settings.ocr.ollama_vision.temperature,
                dpi=self.dpi,
            )
        return self._ocr
    
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
        Perform OCR on an image using Ollama Vision.
        
        Args:
            image: PIL Image to OCR
        
        Returns:
            Extracted text
        """
        ocr = self._get_ocr()
        return ocr.process_image_object(image)
    
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
    
    def close(self) -> None:
        """Close the screen capture."""
        if self._sct is not None:
            self._sct.close()
            self._sct = None
