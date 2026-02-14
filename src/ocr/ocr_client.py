"""
OCR Client for communicating with containerized Tesseract OCR service.
Supports both local Tesseract and remote OCR service via HTTP.
"""

import base64
import io
from pathlib import Path
from typing import Optional

import requests
from PIL import Image

from src.utils import get_logger

logger = get_logger(__name__)


class OCRClient:
    """
    Client for OCR service.
    Can use either local Tesseract or a remote containerized OCR service.
    """
    
    def __init__(
        self,
        service_url: Optional[str] = None,
        languages: list[str] = None,
        dpi: int = 300,
        timeout: int = 120,
        auto_start_container: bool = False,
    ):
        """
        Initialize the OCR client.
        
        Args:
            service_url: URL of the OCR service (e.g., "http://localhost:5000")
                         If None, will attempt to use local Tesseract.
            languages: List of language codes for OCR
            dpi: DPI for image processing
            timeout: Request timeout in seconds
            auto_start_container: Automatically start Docker container if service_url
                                  is set but service is not running
        """
        self.languages = languages or ["eng"]
        self.dpi = dpi
        self.timeout = timeout
        self._local_tesseract = None
        
        # Determine service URL
        self.service_url = service_url
        self.use_remote = service_url is not None
        
        if self.use_remote:
            logger.info(f"Using remote OCR service at {service_url}")
            if not self._verify_service():
                if auto_start_container:
                    logger.info("Attempting to start OCR container...")
                    self.service_url = self._start_container()
                    if self.service_url:
                        self._verify_service()
                    else:
                        logger.warning("Failed to start OCR container, falling back to local Tesseract")
                        self.use_remote = False
                        self._init_local()
                else:
                    logger.warning("OCR service not available, falling back to local Tesseract")
                    self.use_remote = False
                    self._init_local()
        else:
            # Fall back to local Tesseract
            logger.info("Using local Tesseract OCR")
            self._init_local()
    
    def _start_container(self) -> Optional[str]:
        """Start the OCR container using Docker manager."""
        try:
            from src.ocr.docker_manager import ensure_ocr_service
            return ensure_ocr_service(auto_build=True)
        except ImportError as e:
            logger.error(f"Cannot import Docker manager: {e}")
            return None
        except Exception as e:
            logger.error(f"Error starting container: {e}")
            return None
    
    def _verify_service(self) -> bool:
        """Verify that the remote OCR service is accessible."""
        try:
            response = requests.get(
                f"{self.service_url}/health",
                timeout=5
            )
            if response.status_code == 200:
                logger.info("OCR service is healthy")
                return True
            else:
                logger.warning(f"OCR service returned status {response.status_code}")
                return False
        except Exception as e:
            logger.warning(f"Cannot connect to OCR service: {e}")
            return False
    
    def _init_local(self) -> None:
        """Initialize local Tesseract."""
        try:
            import pytesseract
            self._local_tesseract = pytesseract
            version = pytesseract.get_tesseract_version()
            logger.info(f"Local Tesseract version: {version}")
        except ImportError:
            raise RuntimeError(
                "pytesseract is not installed and no remote OCR service configured. "
                "Install with: pip install pytesseract"
            )
        except Exception as e:
            raise RuntimeError(f"Tesseract not available: {e}")
    
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
        
        if self.use_remote:
            return self._process_image_remote(path)
        else:
            return self._process_image_local(path)
    
    def _process_image_remote(self, path: Path) -> str:
        """Process image using remote OCR service."""
        # Read and encode image
        with open(path, "rb") as f:
            image_data = base64.b64encode(f.read()).decode("utf-8")
        
        # Send to service
        response = requests.post(
            f"{self.service_url}/ocr/image",
            json={
                "image": image_data,
                "language": "+".join(self.languages),
                "dpi": self.dpi,
            },
            timeout=self.timeout,
        )
        
        if response.status_code != 200:
            raise RuntimeError(f"OCR service error: {response.text}")
        
        result = response.json()
        return result.get("text", "")
    
    def _process_image_local(self, path: Path) -> str:
        """Process image using local Tesseract."""
        with Image.open(path) as img:
            if img.mode != "RGB":
                img = img.convert("RGB")
            
            text = self._local_tesseract.image_to_string(
                img,
                lang="+".join(self.languages),
                config=f"--dpi {self.dpi}",
            )
        
        return text.strip()
    
    def process_pdf(self, pdf_path: str | Path) -> str:
        """
        Perform OCR on a PDF file.
        
        Args:
            pdf_path: Path to the PDF file
        
        Returns:
            Extracted text
        """
        path = Path(pdf_path)
        
        if not path.exists():
            raise FileNotFoundError(f"PDF file not found: {pdf_path}")
        
        logger.info(f"Processing PDF: {path.name}")
        
        if self.use_remote:
            return self._process_pdf_remote(path)
        else:
            return self._process_pdf_local(path)
    
    def _process_pdf_remote(self, path: Path) -> str:
        """Process PDF using remote OCR service."""
        # Read and encode PDF
        with open(path, "rb") as f:
            pdf_data = base64.b64encode(f.read()).decode("utf-8")
        
        # Send to service
        response = requests.post(
            f"{self.service_url}/ocr/pdf",
            json={
                "pdf": pdf_data,
                "language": "+".join(self.languages),
                "dpi": self.dpi,
            },
            timeout=self.timeout,
        )
        
        if response.status_code != 200:
            raise RuntimeError(f"OCR service error: {response.text}")
        
        result = response.json()
        return result.get("full_text", "")
    
    def _process_pdf_local(self, path: Path) -> str:
        """Process PDF using local Tesseract."""
        from pdf2image import convert_from_path
        
        images = convert_from_path(path, dpi=self.dpi)
        
        text_parts = []
        for page_num, image in enumerate(images, 1):
            if image.mode != "RGB":
                image = image.convert("RGB")
            
            page_text = self._local_tesseract.image_to_string(
                image,
                lang="+".join(self.languages),
                config=f"--dpi {self.dpi}",
            )
            
            if page_text.strip():
                text_parts.append(f"--- Page {page_num} ---\n{page_text.strip()}")
        
        return "\n\n".join(text_parts)
    
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
        if self.use_remote:
            return self._process_image_object_remote(image)
        else:
            return self._process_image_object_local(image)
    
    def _process_image_object_remote(self, image: Image.Image) -> str:
        """Process PIL Image using remote OCR service."""
        # Convert to RGB if necessary
        if image.mode != "RGB":
            image = image.convert("RGB")
        
        # Encode image to base64
        buffer = io.BytesIO()
        image.save(buffer, format="PNG")
        image_data = base64.b64encode(buffer.getvalue()).decode("utf-8")
        
        # Send to service
        response = requests.post(
            f"{self.service_url}/ocr/image",
            json={
                "image": image_data,
                "language": "+".join(self.languages),
                "dpi": self.dpi,
            },
            timeout=self.timeout,
        )
        
        if response.status_code != 200:
            raise RuntimeError(f"OCR service error: {response.text}")
        
        result = response.json()
        return result.get("text", "")
    
    def _process_image_object_local(self, image: Image.Image) -> str:
        """Process PIL Image using local Tesseract."""
        if image.mode != "RGB":
            image = image.convert("RGB")
        
        text = self._local_tesseract.image_to_string(
            image,
            lang="+".join(self.languages),
            config=f"--dpi {self.dpi}",
        )
        
        return text.strip()
    
    def check_service(self) -> dict:
        """
        Check the OCR service status.
        
        Returns:
            Dictionary with service status information
        """
        if self.use_remote:
            try:
                response = requests.get(
                    f"{self.service_url}/health",
                    timeout=5
                )
                if response.status_code == 200:
                    version_response = requests.get(
                        f"{self.service_url}/version",
                        timeout=5
                    )
                    version_info = version_response.json() if version_response.status_code == 200 else {}
                    
                    return {
                        "status": "healthy",
                        "type": "remote",
                        "url": self.service_url,
                        "tesseract_version": version_info.get("tesseract_version", "unknown"),
                    }
                else:
                    return {
                        "status": "unhealthy",
                        "type": "remote",
                        "url": self.service_url,
                        "error": f"HTTP {response.status_code}",
                    }
            except Exception as e:
                return {
                    "status": "error",
                    "type": "remote",
                    "url": self.service_url,
                    "error": str(e),
                }
        else:
            try:
                version = self._local_tesseract.get_tesseract_version()
                return {
                    "status": "healthy",
                    "type": "local",
                    "tesseract_version": str(version),
                }
            except Exception as e:
                return {
                    "status": "error",
                    "type": "local",
                    "error": str(e),
                }