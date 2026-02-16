"""
Tax guidance knowledge base loader.
Loads tax filing instructions and guidance into Qdrant for RAG queries.
"""

import re
from pathlib import Path
from typing import Optional

from src.storage import QdrantHandler, DocumentType
from src.storage.models import ProcessingStatus
from src.utils import get_logger
from src.utils.config import get_settings

logger = get_logger(__name__)


class TaxGuidanceLoader:
    """Load tax guidance documents into Qdrant for RAG queries."""
    
    def __init__(self, qdrant: Optional[QdrantHandler] = None):
        """
        Initialize the guidance loader.
        
        Args:
            qdrant: QdrantHandler instance (creates new if None)
        """
        if qdrant is None:
            qdrant = QdrantHandler()
        self.qdrant = qdrant
        
    def load_text_file(
        self,
        file_path: Path,
        jurisdiction: str,
        tax_year: int,
        document_type: str,
        chunk_size: int = 1000,
    ) -> int:
        """
        Load a text file into Qdrant, chunking it for better retrieval.
        
        Args:
            file_path: Path to the text file
            jurisdiction: "federal", "ca", or "az"
            tax_year: Tax year (e.g., 2025)
            document_type: Type of document (e.g., "form_1040_instructions")
            chunk_size: Size of text chunks
            
        Returns:
            Number of chunks stored
        """
        logger.info(f"Loading {file_path} for {jurisdiction} {tax_year}")
        
        text = file_path.read_text(encoding='utf-8')
        chunks = self._chunk_text(text, chunk_size)
        
        for i, chunk in enumerate(chunks):
            # Create a unique document ID for each chunk
            # Use negative IDs to distinguish from tax documents
            doc_id = -(tax_year * 1000000 + hash(f"{jurisdiction}_{document_type}_{i}"))
            
            self.qdrant.store_document(
                document_id=doc_id,
                ocr_text=chunk,
                document_type=DocumentType.UNKNOWN,  # Use UNKNOWN for guidance docs
                tax_year=tax_year,
                file_name=f"{jurisdiction}_{document_type}_chunk_{i}.txt",
                extracted_fields={
                    "jurisdiction": jurisdiction,
                    "document_type": document_type,
                    "chunk_index": i,
                    "total_chunks": len(chunks),
                    "is_guidance": True,
                }
            )
        
        logger.info(f"Stored {len(chunks)} chunks from {file_path.name}")
        return len(chunks)
    
    def load_pdf_file(
        self,
        file_path: Path,
        jurisdiction: str,
        tax_year: int,
        document_type: str,
        chunk_size: int = 1000,
    ) -> int:
        """
        Load a PDF file (extracted text) into Qdrant.
        
        Args:
            file_path: Path to the PDF file
            jurisdiction: "federal", "ca", or "az"
            tax_year: Tax year
            document_type: Type of document
            chunk_size: Size of text chunks
            
        Returns:
            Number of chunks stored
        """
        logger.info(f"Loading PDF {file_path} for {jurisdiction} {tax_year}")
        
        try:
            from pdf2image import convert_from_path
            import pytesseract
            from PIL import Image
            
            # Convert PDF to images and OCR
            images = convert_from_path(file_path, dpi=200)
            full_text = ""
            
            for i, image in enumerate(images):
                text = pytesseract.image_to_string(image)
                full_text += f"\n--- Page {i+1} ---\n{text}"
            
            chunks = self._chunk_text(full_text, chunk_size)
            
            for i, chunk in enumerate(chunks):
                doc_id = -(tax_year * 1000000 + hash(f"{jurisdiction}_{document_type}_{i}"))
                
                self.qdrant.store_document(
                    document_id=doc_id,
                    ocr_text=chunk,
                    document_type=DocumentType.UNKNOWN,
                    tax_year=tax_year,
                    file_name=f"{jurisdiction}_{document_type}_chunk_{i}.txt",
                    extracted_fields={
                        "jurisdiction": jurisdiction,
                        "document_type": document_type,
                        "chunk_index": i,
                        "total_chunks": len(chunks),
                        "is_guidance": True,
                        "source_file": file_path.name,
                    }
                )
            
            logger.info(f"Stored {len(chunks)} chunks from PDF {file_path.name}")
            return len(chunks)
            
        except ImportError:
            logger.error("pdf2image or pytesseract not installed. Cannot process PDF.")
            return 0
        except Exception as e:
            logger.error(f"Error processing PDF {file_path}: {e}")
            return 0
    
    def load_directory(
        self,
        directory: Path,
        jurisdiction: str,
        tax_year: int,
        chunk_size: int = 1000,
    ) -> int:
        """
        Load all text and PDF files from a directory.
        
        Args:
            directory: Directory containing tax guidance files
            jurisdiction: "federal", "ca", or "az"
            tax_year: Tax year
            chunk_size: Size of text chunks
            
        Returns:
            Total number of chunks stored
        """
        total_chunks = 0
        
        for file_path in directory.iterdir():
            if file_path.is_file():
                document_type = file_path.stem
                
                if file_path.suffix.lower() == '.txt':
                    count = self.load_text_file(
                        file_path, jurisdiction, tax_year, document_type, chunk_size
                    )
                    total_chunks += count
                    
                elif file_path.suffix.lower() == '.pdf':
                    count = self.load_pdf_file(
                        file_path, jurisdiction, tax_year, document_type, chunk_size
                    )
                    total_chunks += count
        
        logger.info(f"Total chunks loaded from {directory}: {total_chunks}")
        return total_chunks
    
    def _chunk_text(self, text: str, chunk_size: int = 1000) -> list[str]:
        """
        Split text into chunks while preserving context.
        
        Args:
            text: Text to chunk
            chunk_size: Target size of each chunk
            
        Returns:
            List of text chunks
        """
        # Clean up whitespace
        text = re.sub(r'\n+', '\n', text)
        text = re.sub(r' +', ' ', text)
        
        chunks = []
        current_chunk = ""
        
        # Split by paragraphs first
        paragraphs = text.split('\n\n')
        
        for para in paragraphs:
            if len(current_chunk) + len(para) < chunk_size:
                current_chunk += para + "\n\n"
            else:
                if current_chunk:
                    chunks.append(current_chunk.strip())
                current_chunk = para + "\n\n"
        
        if current_chunk:
            chunks.append(current_chunk.strip())
        
        return chunks if chunks else [text]
    
    def search_guidance(
        self,
        query: str,
        jurisdiction: Optional[str] = None,
        tax_year: Optional[int] = None,
        limit: int = 5,
    ) -> list[dict]:
        """
        Search for tax guidance.
        
        Args:
            query: Search query
            jurisdiction: Filter by jurisdiction (federal, ca, az)
            tax_year: Filter by tax year
            limit: Maximum results
            
        Returns:
            List of matching guidance chunks
        """
        # Search in Qdrant
        results = self.qdrant.search(query, limit=limit * 2, tax_year=tax_year)
        
        # Filter for guidance documents
        guidance_results = []
        for result in results:
            fields = result.get("extracted_fields", {})
            if fields.get("is_guidance"):
                if jurisdiction is None or fields.get("jurisdiction") == jurisdiction:
                    guidance_results.append(result)
        
        return guidance_results[:limit]
    
    def get_context_for_query(
        self,
        query: str,
        tax_year: int,
        jurisdiction: Optional[str] = None,
        max_chunks: int = 3,
    ) -> str:
        """
        Get relevant tax guidance context for a query.
        
        Args:
            query: User query
            tax_year: Tax year
            jurisdiction: Specific jurisdiction or None for all
            max_chunks: Maximum chunks to include
            
        Returns:
            Combined context string
        """
        results = self.search_guidance(query, jurisdiction, tax_year, max_chunks)
        
        if not results:
            return ""
        
        context_parts = ["\n=== Tax Filing Guidance ===\n"]
        
        for i, result in enumerate(results, 1):
            fields = result.get("extracted_fields", {})
            jurisdiction_label = fields.get("jurisdiction", "unknown").upper()
            doc_type = fields.get("document_type", "guidance")
            
            context_parts.append(
                f"\n[{i}] {jurisdiction_label} - {doc_type}\n"
                f"{result.get('ocr_text', '')[:800]}...\n"
            )
        
        return "\n".join(context_parts)


JURISDICTION_DIR_MAP = {
    "federal": "federal",
    "ca": "ca", 
    "az": "az",
}


def auto_load_tax_guidance(
    tax_year: int,
    data_dir: Path = Path("data"),
    chunk_size: int = 1000,
) -> dict:
    """
    Automatically load tax guidance from standard directories.
    
    Looks for:
    - data/federal/
    - data/ca/
    - data/az/
    
    Args:
        tax_year: Tax year to load guidance for
        data_dir: Base data directory
        chunk_size: Size of text chunks
        
    Returns:
        Dictionary with loaded counts per jurisdiction
    """
    from src.storage.qdrant_manager import QdrantManager
    from src.utils import get_logger
    
    logger = get_logger(__name__)
    
    results = {}
    
    # Ensure Qdrant is running
    try:
        manager = QdrantManager()
        if not manager.is_container_running():
            logger.info("Starting Qdrant for tax guidance...")
            manager.ensure_service_running(auto_pull=True)
    except Exception as e:
        logger.warning(f"Could not start Qdrant: {e}")
        return results
    
    loader = TaxGuidanceLoader()
    
    for jurisdiction, dir_name in JURISDICTION_DIR_MAP.items():
        guidance_dir = data_dir / dir_name
        
        if not guidance_dir.exists():
            logger.debug(f"Guidance directory not found: {guidance_dir}")
            continue
        
        # Check if directory has files
        files = list(guidance_dir.iterdir())
        if not files:
            logger.debug(f"No files in {guidance_dir}")
            continue
        
        logger.info(f"Loading {jurisdiction} guidance from {guidance_dir}...")
        
        try:
            chunk_count = loader.load_directory(guidance_dir, jurisdiction, tax_year, chunk_size)
            results[jurisdiction] = chunk_count
            logger.info(f"Loaded {chunk_count} chunks for {jurisdiction}")
        except Exception as e:
            logger.error(f"Error loading {jurisdiction} guidance: {e}")
            results[jurisdiction] = 0
    
    return results


def load_tax_guidance(
    guidance_dir: Path,
    jurisdiction: str,
    tax_year: int,
) -> int:
    """
    Convenience function to load tax guidance.
    
    Args:
        guidance_dir: Directory with guidance files
        jurisdiction: "federal", "ca", or "az"
        tax_year: Tax year
        
    Returns:
        Number of chunks loaded
    """
    loader = TaxGuidanceLoader()
    return loader.load_directory(guidance_dir, jurisdiction, tax_year)
