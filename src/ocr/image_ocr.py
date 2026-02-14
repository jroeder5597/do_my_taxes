"""
Image OCR module.
Handles OCR for images and scanned PDF documents using Tesseract.
"""

import tempfile
from pathlib import Path
from typing import Optional

from pdf2image import convert_from_path
from PIL import Image

from src.utils import get_logger

logger = get_logger(__name__)

# Try to import pytesseract, handle if not installed
try:
    import pytesseract
    TESSERACT_AVAILABLE = True
except ImportError:
    TESSERACT_AVAILABLE = False
    logger.warning("pytesseract not installed. OCR functionality will be limited.")


class ImageOCR:
    """
    OCR processor for images and scanned documents.
    Uses Tesseract OCR engine.
    """
    
    def __init__(
        self,
        tesseract_path: Optional[str] = None,
        languages: list[str] = None,
        dpi: int = 300,
    ):
        """
        Initialize the OCR processor.
        
        Args:
            tesseract_path: Path to Tesseract executable (Windows)
            languages: List of language codes for OCR
            dpi: DPI for image processing
        """
        if not TESSERACT_AVAILABLE:
            raise RuntimeError("pytesseract is not installed. Install with: pip install pytesseract")
        
        self.languages = languages or ["eng"]
        self.dpi = dpi
        
        # Set Tesseract path if provided (needed for Windows)
        if tesseract_path:
            pytesseract.pytesseract.tesseract_cmd = tesseract_path
        
        # Verify Tesseract is available
        self._verify_tesseract()
    
    def _verify_tesseract(self) -> None:
        """Verify that Tesseract is installed and accessible."""
        try:
            version = pytesseract.get_tesseract_version()
            logger.info(f"Tesseract version: {version}")
        except Exception as e:
            raise RuntimeError(
                f"Tesseract is not installed or not in PATH. "
                f"Please install Tesseract OCR. Error: {e}"
            )
    
    def process_image(self, image_path: str | Path) -> str:
        """
        Perform OCR on an image file.
        
        Args:
            image_path: Path to the image file
        
        Returns:
            Extracted text
        """
        path = Path(image_path)
        
        if not path.exists():
            raise FileNotFoundError(f"Image file not found: {image_path}")
        
        logger.info(f"Processing image: {path.name}")
        
        try:
            # Open and process the image
            with Image.open(path) as img:
                # Convert to RGB if necessary
                if img.mode != "RGB":
                    img = img.convert("RGB")
                
                # Set DPI for better OCR
                img.info["dpi"] = (self.dpi, self.dpi)
                
                # Perform OCR
                text = pytesseract.image_to_string(
                    img,
                    lang="+".join(self.languages),
                    config=f"--dpi {self.dpi}",
                )
            
            logger.info(f"OCR completed for {path.name}")
            return text.strip()
        
        except Exception as e:
            logger.error(f"OCR failed for {path.name}: {e}")
            raise
    
    def process_pdf(self, pdf_path: str | Path) -> str:
        """
        Perform OCR on a scanned PDF file.
        Converts PDF pages to images and then performs OCR.
        
        Args:
            pdf_path: Path to the PDF file
        
        Returns:
            Extracted text
        """
        path = Path(pdf_path)
        
        if not path.exists():
            raise FileNotFoundError(f"PDF file not found: {pdf_path}")
        
        logger.info(f"Processing scanned PDF: {path.name}")
        
        text_parts = []
        
        try:
            # Convert PDF pages to images
            images = convert_from_path(
                path,
                dpi=self.dpi,
            )
            
            logger.info(f"Converted {path.name} to {len(images)} images")
            
            # Process each page
            for page_num, image in enumerate(images, 1):
                logger.debug(f"Processing page {page_num}")
                
                # Convert to RGB if necessary
                if image.mode != "RGB":
                    image = image.convert("RGB")
                
                # Perform OCR on the page
                page_text = pytesseract.image_to_string(
                    image,
                    lang="+".join(self.languages),
                    config=f"--dpi {self.dpi}",
                )
                
                if page_text.strip():
                    text_parts.append(f"--- Page {page_num} ---\n{page_text.strip()}")
            
            logger.info(f"OCR completed for {path.name}")
            return "\n\n".join(text_parts)
        
        except Exception as e:
            logger.error(f"PDF OCR failed for {path.name}: {e}")
            raise
    
    def process_file(self, file_path: str | Path) -> str:
        """
        Process a file (image or PDF) and extract text.
        
        Args:
            file_path: Path to the file
        
        Returns:
            Extracted text
        """
        path = Path(file_path)
        suffix = path.suffix.lower()
        
        if suffix == ".pdf":
            return self.process_pdf(path)
        elif suffix in [".png", ".jpg", ".jpeg", ".tiff", ".tif", ".bmp"]:
            return self.process_image(path)
        else:
            raise ValueError(f"Unsupported file format: {suffix}")
    
    def process_image_object(self, image: Image.Image) -> str:
        """
        Perform OCR on a PIL Image object.
        
        Args:
            image: PIL Image object
        
        Returns:
            Extracted text
        """
        try:
            # Convert to RGB if necessary
            if image.mode != "RGB":
                image = image.convert("RGB")
            
            # Perform OCR
            text = pytesseract.image_to_string(
                image,
                lang="+".join(self.languages),
                config=f"--dpi {self.dpi}",
            )
            
            return text.strip()
        
        except Exception as e:
            logger.error(f"OCR failed for image object: {e}")
            raise
    
    def get_ocr_confidence(self, image_path: str | Path) -> dict:
        """
        Get OCR confidence data for an image.
        
        Args:
            image_path: Path to the image file
        
        Returns:
            Dictionary with confidence statistics
        """
        path = Path(image_path)
        
        try:
            with Image.open(path) as img:
                if img.mode != "RGB":
                    img = img.convert("RGB")
                
                # Get detailed OCR data
                data = pytesseract.image_to_data(
                    img,
                    lang="+".join(self.languages),
                    output_type=pytesseract.Output.DICT,
                )
            
            # Calculate confidence statistics
            confidences = [int(c) for c in data.get("conf", []) if c != "-1"]
            
            if not confidences:
                return {"average": 0, "min": 0, "max": 0, "word_count": 0}
            
            return {
                "average": sum(confidences) / len(confidences),
                "min": min(confidences),
                "max": max(confidences),
                "word_count": len(confidences),
            }
        
        except Exception as e:
            logger.error(f"Failed to get OCR confidence for {path.name}: {e}")
            return {"average": 0, "min": 0, "max": 0, "word_count": 0, "error": str(e)}