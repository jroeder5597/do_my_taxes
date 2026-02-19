"""
PDF text extraction module.
Handles both digital PDFs with embedded text and scanned PDFs.
"""

from pathlib import Path
from typing import Optional

import pdfplumber
from PyPDF2 import PdfReader

from src.utils import get_logger

logger = get_logger(__name__)


class PDFProcessor:
    """
    Process PDF files to extract text.
    Handles both digital PDFs (with embedded text) and scanned PDFs.
    """
    
    def __init__(self, dpi: int = 300, use_flyfield: bool = True):
        """
        Initialize the PDF processor.
        
        Args:
            dpi: DPI for PDF to image conversion (for scanned PDFs)
            use_flyfield: Use flyfield service for better extraction
        """
        self.dpi = dpi
        self.use_flyfield = use_flyfield
        self._flyfield_extractor = None
    
    def _get_flyfield_extractor(self):
        """Lazy load flyfield extractor."""
        if self._flyfield_extractor is None:
            try:
                from src.ocr.flyfield_extractor import FlyfieldExtractor
                self._flyfield_extractor = FlyfieldExtractor()
            except Exception as e:
                logger.debug(f"Flyfield extractor not available: {e}")
        return self._flyfield_extractor
    
    def extract_text(self, pdf_path: str | Path) -> str:
        """
        Extract text from a PDF file.
        First attempts digital text extraction, then falls back to OCR if needed.
        
        Args:
            pdf_path: Path to the PDF file
        
        Returns:
            Extracted text content
        """
        path = Path(pdf_path)
        
        if not path.exists():
            raise FileNotFoundError(f"PDF file not found: {pdf_path}")
        
        if path.suffix.lower() != ".pdf":
            raise ValueError(f"File is not a PDF: {pdf_path}")
        
        logger.info(f"Processing PDF: {path.name}")
        
        # First, try digital text extraction
        text = self._extract_digital_text(path)
        
        if text and self._is_valid_text(text):
            logger.info(f"Successfully extracted digital text from {path.name}")
            return text
        
        # If no valid text found, the PDF is likely scanned
        logger.info(f"No digital text found in {path.name}, PDF may be scanned")
        return ""  # Will be handled by flyfield extractor
    
    def _extract_digital_text(self, pdf_path: Path) -> str:
        """
        Extract embedded text from a digital PDF.
        
        Args:
            pdf_path: Path to the PDF file
        
        Returns:
            Extracted text content
        """
        text_parts = []
        
        try:
            # Use pdfplumber for better text extraction
            with pdfplumber.open(pdf_path) as pdf:
                for page_num, page in enumerate(pdf.pages, 1):
                    page_text = page.extract_text()
                    if page_text:
                        text_parts.append(f"--- Page {page_num} ---\n{page_text}")
        
        except Exception as e:
            logger.warning(f"pdfplumber extraction failed for {pdf_path.name}: {e}")
            
            # Fallback to PyPDF2
            try:
                reader = PdfReader(pdf_path)
                for page_num, page in enumerate(reader.pages, 1):
                    page_text = page.extract_text()
                    if page_text:
                        text_parts.append(f"--- Page {page_num} ---\n{page_text}")
            except Exception as e2:
                logger.error(f"PyPDF2 extraction also failed for {pdf_path.name}: {e2}")
        
        return "\n\n".join(text_parts)
    
    def _is_valid_text(self, text: str) -> bool:
        """
        Check if extracted text is valid (not just whitespace or garbage).
        
        Args:
            text: Extracted text
        
        Returns:
            True if text appears to be valid content
        """
        if not text:
            return False
        
        # Remove whitespace and check length
        cleaned = text.strip()
        
        if len(cleaned) < 50:
            return False
        
        # Check for common tax document keywords
        tax_keywords = [
            "wage", "tax", "income", "employer", "employee", "ssn", "ein",
            "federal", "state", "withhold", "compensation", "interest",
            "dividend", "payer", "recipient", "1099", "w-2", "w2"
        ]
        
        text_lower = text.lower()
        keyword_count = sum(1 for kw in tax_keywords if kw in text_lower)
        
        # If we find at least 2 tax-related keywords, it's likely valid
        return keyword_count >= 2
    
    def get_page_count(self, pdf_path: str | Path) -> int:
        """
        Get the number of pages in a PDF.
        
        Args:
            pdf_path: Path to the PDF file
        
        Returns:
            Number of pages
        """
        path = Path(pdf_path)
        
        try:
            reader = PdfReader(path)
            return len(reader.pages)
        except Exception as e:
            logger.error(f"Failed to get page count for {path.name}: {e}")
            return 0
    
    def get_pdf_info(self, pdf_path: str | Path) -> dict:
        """
        Get information about a PDF file.
        
        Args:
            pdf_path: Path to the PDF file
        
        Returns:
            Dictionary with PDF information
        """
        path = Path(pdf_path)
        
        if not path.exists():
            raise FileNotFoundError(f"PDF file not found: {pdf_path}")
        
        info = {
            "file_name": path.name,
            "file_size_bytes": path.stat().st_size,
            "page_count": 0,
            "is_scanned": False,
            "has_text": False,
            "metadata": {},
        }
        
        try:
            reader = PdfReader(path)
            info["page_count"] = len(reader.pages)
            
            # Check metadata
            if reader.metadata:
                info["metadata"] = {
                    "title": reader.metadata.get("/Title", ""),
                    "author": reader.metadata.get("/Author", ""),
                    "creator": reader.metadata.get("/Creator", ""),
                    "producer": reader.metadata.get("/Producer", ""),
                }
            
            # Check if PDF has embedded text
            text = self._extract_digital_text(path)
            info["has_text"] = bool(text and self._is_valid_text(text))
            info["is_scanned"] = not info["has_text"]
        
        except Exception as e:
            logger.error(f"Failed to get PDF info for {path.name}: {e}")
        
        return info
    
    def is_scanned_pdf(self, pdf_path: str | Path) -> bool:
        """
        Check if a PDF is scanned (no embedded text).
        
        Args:
            pdf_path: Path to the PDF file
        
        Returns:
            True if the PDF appears to be scanned
        """
        text = self._extract_digital_text(Path(pdf_path))
        return not self._is_valid_text(text)