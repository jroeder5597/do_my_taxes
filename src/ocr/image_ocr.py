"""
Image OCR module using Tesseract via container service.
"""

from pathlib import Path
from typing import Optional

from src.utils import get_logger
from src.utils.config import get_settings
from src.ocr.ocr_client import OCRClient

logger = get_logger(__name__)


class ImageOCR:
    """
    OCR processor using Tesseract via container service.
    """

    def __init__(
        self,
        service_url: Optional[str] = None,
        language: str = "eng",
        dpi: int = 300,
    ):
        """
        Initialize the OCR processor.

        Args:
            service_url: URL of the OCR service
            language: OCR language code
            dpi: DPI for PDF to image conversion
        """
        settings = get_settings()
        self.client = OCRClient(service_url or settings.ocr.service_url)
        self.language = language
        self.dpi = dpi

    def process_image(self, image_path: str | Path) -> str:
        """
        Perform OCR on an image file.

        Args:
            image_path: Path to the image file

        Returns:
            Extracted text
        """
        return self.client.ocr_image(image_path, language=self.language)

    def process_pdf(self, pdf_path: str | Path) -> str:
        """
        Perform OCR on a PDF file.

        Args:
            pdf_path: Path to the PDF file

        Returns:
            Extracted text
        """
        return self.client.ocr_pdf(pdf_path, language=self.language, dpi=self.dpi)

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
