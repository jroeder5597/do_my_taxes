"""
OCR Client for communicating with the Tesseract OCR service.
"""

import base64
from pathlib import Path
from typing import Optional

import requests

from src.utils import get_logger
from src.utils.config import get_settings

logger = get_logger(__name__)


class OCRClient:
    """
    Client for the Tesseract OCR container service.
    """

    def __init__(self, service_url: Optional[str] = None):
        """
        Initialize the OCR client.

        Args:
            service_url: URL of the OCR service (e.g., "http://localhost:5000")
        """
        settings = get_settings()
        self.service_url = service_url or settings.ocr.service_url

        if not self.service_url:
            raise ValueError("OCR service URL not configured")

        # Remove trailing slash
        self.service_url = self.service_url.rstrip("/")

    def check_health(self) -> bool:
        """
        Check if the OCR service is healthy.

        Returns:
            True if service is healthy
        """
        try:
            response = requests.get(f"{self.service_url}/health", timeout=5)
            return response.status_code == 200
        except requests.exceptions.RequestException:
            return False

    def ocr_image(self, image_path: str | Path, language: str = "eng") -> str:
        """
        Perform OCR on an image file.

        Args:
            image_path: Path to the image file
            language: OCR language code

        Returns:
            Extracted text
        """
        path = Path(image_path)

        if not path.exists():
            raise FileNotFoundError(f"Image file not found: {image_path}")

        logger.info(f"OCR on image: {path.name}")

        try:
            with open(path, "rb") as f:
                files = {"file": (path.name, f, "image/png")}
                data = {"language": language}

                response = requests.post(
                    f"{self.service_url}/ocr/file",
                    files=files,
                    data=data,
                    timeout=60,
                )

                response.raise_for_status()
                result = response.json()

                if result.get("success"):
                    return result.get("text", "")
                else:
                    raise RuntimeError(f"OCR failed: {result.get('error', 'Unknown error')}")

        except requests.exceptions.RequestException as e:
            logger.error(f"OCR request failed: {e}")
            raise

    def ocr_pdf(self, pdf_path: str | Path, language: str = "eng", dpi: int = 300) -> str:
        """
        Perform OCR on a PDF file.

        Args:
            pdf_path: Path to the PDF file
            language: OCR language code
            dpi: DPI for PDF to image conversion

        Returns:
            Extracted text
        """
        path = Path(pdf_path)

        if not path.exists():
            raise FileNotFoundError(f"PDF file not found: {pdf_path}")

        logger.info(f"OCR on PDF: {path.name}")

        try:
            with open(path, "rb") as f:
                files = {"file": (path.name, f, "application/pdf")}
                data = {"language": language, "dpi": dpi}

                response = requests.post(
                    f"{self.service_url}/ocr/file",
                    files=files,
                    data=data,
                    timeout=120,
                )

                response.raise_for_status()
                result = response.json()

                if result.get("success"):
                    return result.get("text", "")
                else:
                    raise RuntimeError(f"OCR failed: {result.get('error', 'Unknown error')}")

        except requests.exceptions.RequestException as e:
            logger.error(f"OCR request failed: {e}")
            raise

    def ocr_batch(self, file_paths: list[str | Path], language: str = "eng") -> list[dict]:
        """
        Perform OCR on multiple files.

        Args:
            file_paths: List of file paths
            language: OCR language code

        Returns:
            List of results with 'filename', 'success', 'text', and optionally 'error'
        """
        logger.info(f"Batch OCR on {len(file_paths)} files")

        files = []
        for path_str in file_paths:
            path = Path(path_str)
            if path.exists():
                files.append(("files", (path.name, open(path, "rb"))))

        if not files:
            return []

        try:
            data = {"language": language}

            response = requests.post(
                f"{self.service_url}/ocr/batch",
                files=files,
                data=data,
                timeout=300,
            )

            # Close all files
            for _, file_tuple in files:
                file_tuple[1].close()

            response.raise_for_status()
            result = response.json()

            if result.get("success"):
                return result.get("results", [])
            else:
                raise RuntimeError(f"Batch OCR failed: {result.get('error', 'Unknown error')}")

        except requests.exceptions.RequestException as e:
            logger.error(f"Batch OCR request failed: {e}")
            raise
