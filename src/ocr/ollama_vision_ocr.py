"""
Ollama Vision-based OCR client.
Uses Ollama vision models (like granite3.2-vision) to extract text from images and documents.
Replaces Tesseract OCR with vision-capable LLMs for better accuracy on tax documents.
"""

import base64
import io
from pathlib import Path
from typing import Optional

from PIL import Image

from src.utils import get_logger
from src.utils.config import get_settings

logger = get_logger(__name__)

# Try to import ollama
try:
    import ollama
    OLLAMA_AVAILABLE = True
except ImportError:
    OLLAMA_AVAILABLE = False
    logger.warning("ollama package not installed. Ollama Vision OCR will not be available.")

# Try to import pdf2image (requires poppler)
try:
    from pdf2image import convert_from_path
    PDF2IMAGE_AVAILABLE = True
except ImportError:
    PDF2IMAGE_AVAILABLE = False

# Try to import PyMuPDF (fallback for PDF rendering)
try:
    import fitz  # PyMuPDF
    PYMUPDF_AVAILABLE = True
except ImportError:
    PYMUPDF_AVAILABLE = False


class OllamaVisionOCR:
    """
    OCR processor using Ollama Vision models.
    Supports vision-capable models like granite3.2-vision for document text extraction.
    """
    
    # Default system prompt for OCR extraction
    OCR_SYSTEM_PROMPT = """You are an expert OCR (Optical Character Recognition) system.
Your task is to extract all text from the provided image accurately.

Instructions:
1. Extract ALL text visible in the image, preserving the layout as much as possible
2. Maintain the structure of forms, tables, and fields
3. Preserve line breaks and spacing where meaningful
4. Extract numbers, dates, codes, and identifiers exactly as shown
5. If text is unclear or ambiguous, make your best interpretation and note it
6. Return ONLY the extracted text, no explanations or formatting notes

Focus on accuracy, especially for:
- Tax form numbers and box values
- Employer and employee information
- Financial amounts and percentages
- Dates and identification numbers
"""
    
    def __init__(
        self,
        model: Optional[str] = None,
        base_url: Optional[str] = None,
        dpi: int = 300,
        temperature: float = 0.1,
    ):
        """
        Initialize the Ollama Vision OCR processor.
        
        Args:
            model: Ollama vision model name (e.g., "granite3.2-vision:latest")
            base_url: Ollama API base URL
            dpi: DPI for PDF to image conversion
            temperature: Temperature for generation (lower = more deterministic)
        """
        if not OLLAMA_AVAILABLE:
            raise RuntimeError(
                "ollama package is not installed. Install with: pip install ollama"
            )
        
        # Get settings from config
        settings = get_settings()
        
        self.model = model or settings.ocr.ollama_vision.model
        self.base_url = base_url or settings.llm.ollama.base_url
        self.dpi = dpi
        self.temperature = temperature
        
        # Configure ollama client
        self.client = ollama.Client(host=self.base_url)
        
        # Verify model is available
        self._verify_model()
    
    def _verify_model(self) -> None:
        """Verify that the vision model is available in Ollama."""
        try:
            models = self.client.list()
            model_names = [m.get("model", "") for m in models.get("models", [])]
            
            # Check if model exists (with or without tag)
            model_base = self.model.split(":")[0]
            model_available = any(
                m == self.model or m.startswith(f"{model_base}:") or m == model_base
                for m in model_names
            )
            
            if not model_available:
                logger.warning(
                    f"Model '{self.model}' not found in Ollama. "
                    f"Available models: {model_names}. "
                    f"You may need to pull the model: ollama pull {self.model}"
                )
        except Exception as e:
            logger.warning(f"Could not verify model availability: {e}")
    
    def _encode_image(self, image: Image.Image) -> str:
        """
        Encode a PIL Image to base64 string.
        
        Args:
            image: PIL Image object
            
        Returns:
            Base64 encoded image string
        """
        # Convert to RGB if necessary
        if image.mode != "RGB":
            image = image.convert("RGB")
        
        # Encode to base64
        buffer = io.BytesIO()
        image.save(buffer, format="PNG")
        return base64.b64encode(buffer.getvalue()).decode("utf-8")
    
    def _extract_text_from_image(self, image: Image.Image) -> str:
        """
        Extract text from a PIL Image using Ollama Vision.
        
        Args:
            image: PIL Image object
            
        Returns:
            Extracted text
        """
        try:
            # Encode image to base64
            image_b64 = self._encode_image(image)
            
            # Call Ollama Vision API
            response = self.client.chat(
                model=self.model,
                messages=[
                    {
                        "role": "system",
                        "content": self.OCR_SYSTEM_PROMPT,
                    },
                    {
                        "role": "user",
                        "content": "Extract all text from this document image:",
                        "images": [image_b64],
                    },
                ],
                options={
                    "temperature": self.temperature,
                },
            )
            
            # Extract text from response
            text = response.get("message", {}).get("content", "").strip()
            
            return text
            
        except Exception as e:
            logger.error(f"Ollama Vision OCR failed: {e}")
            raise
    
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
        
        logger.info(f"Processing image with Ollama Vision: {path.name}")
        
        try:
            # Open the image
            with Image.open(path) as img:
                text = self._extract_text_from_image(img)
            
            logger.info(f"OCR completed for {path.name}")
            return text
            
        except Exception as e:
            logger.error(f"OCR failed for {path.name}: {e}")
            raise
    
    def _pdf_to_images_with_pymupdf(self, pdf_path: Path) -> list[Image.Image]:
        """
        Convert PDF pages to images using PyMuPDF (fallback method).
        
        Args:
            pdf_path: Path to the PDF file
            
        Returns:
            List of PIL Images
        """
        images = []
        doc = fitz.open(pdf_path)
        
        for page_num in range(len(doc)):
            page = doc.load_page(page_num)
            # Render at specified DPI
            mat = fitz.Matrix(self.dpi/72, self.dpi/72)  # 72 is the default PDF DPI
            pix = page.get_pixmap(matrix=mat)
            
            # Convert to PIL Image
            img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
            images.append(img)
        
        doc.close()
        return images
    
    def _pdf_to_images(self, pdf_path: Path) -> list[Image.Image]:
        """
        Convert PDF pages to images.
        Tries pdf2image first, falls back to PyMuPDF.
        
        Args:
            pdf_path: Path to the PDF file
            
        Returns:
            List of PIL Images
        """
        if PDF2IMAGE_AVAILABLE:
            try:
                return convert_from_path(pdf_path, dpi=self.dpi)
            except Exception as e:
                logger.warning(f"pdf2image failed, trying PyMuPDF fallback: {e}")
        
        if PYMUPDF_AVAILABLE:
            return self._pdf_to_images_with_pymupdf(pdf_path)
        
        raise RuntimeError(
            "No PDF rendering library available. "
            "Install poppler (for pdf2image) or PyMuPDF: pip install pymupdf"
        )
    
    def process_pdf(self, pdf_path: str | Path) -> str:
        """
        Perform OCR on a scanned PDF file.
        Converts PDF pages to images and then performs OCR.
        
        Args:
            pdf_path: Path to the PDF file
            
        Returns:
            Extracted text from all pages
        """
        path = Path(pdf_path)
        
        if not path.exists():
            raise FileNotFoundError(f"PDF file not found: {pdf_path}")
        
        logger.info(f"Processing PDF with Ollama Vision: {path.name}")
        
        text_parts = []
        
        try:
            # Convert PDF pages to images
            images = self._pdf_to_images(path)
            
            logger.info(f"Converted {path.name} to {len(images)} images")
            
            # Process each page
            for page_num, image in enumerate(images, 1):
                logger.debug(f"Processing page {page_num}")
                
                page_text = self._extract_text_from_image(image)
                
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
        return self._extract_text_from_image(image)
    
    def check_connection(self) -> bool:
        """
        Check if Ollama is running and accessible.
        
        Returns:
            True if connection is successful
        """
        try:
            self.client.list()
            return True
        except Exception as e:
            logger.error(f"Failed to connect to Ollama: {e}")
            return False
    
    def check_model(self) -> dict:
        """
        Check the vision model status.
        
        Returns:
            Dictionary with model status information
        """
        result = {
            "connection": False,
            "model_available": False,
            "model_name": self.model,
            "base_url": self.base_url,
        }
        
        try:
            # Check connection
            models = self.client.list()
            result["connection"] = True
            
            # Check if model exists
            model_names = [m.get("model", "") for m in models.get("models", [])]
            model_base = self.model.split(":")[0]
            result["model_available"] = any(
                m == self.model or m.startswith(f"{model_base}:") or m == model_base
                for m in model_names
            )
            result["available_models"] = model_names
            
        except Exception as e:
            result["error"] = str(e)
        
        return result
