"""
Qdrant vector database handler for tax document embeddings.
Enables semantic search and RAG queries over tax documents.
"""

import uuid
from typing import Any, Optional

from src.storage.models import DocumentType
from src.utils import get_logger

logger = get_logger(__name__)

# Try to import dependencies
try:
    from qdrant_client import QdrantClient
    from qdrant_client.models import (
        Distance,
        PointStruct,
        VectorParams,
        Filter,
        FieldCondition,
        MatchValue,
    )
    QDRANT_AVAILABLE = True
except ImportError:
    QDRANT_AVAILABLE = False
    logger.warning("qdrant-client not installed. Vector storage will not be available.")

try:
    from sentence_transformers import SentenceTransformer
    EMBEDDINGS_AVAILABLE = True
except ImportError:
    EMBEDDINGS_AVAILABLE = False
    logger.warning("sentence-transformers not installed. Local embeddings will not be available.")


class QdrantHandler:
    """
    Handle vector storage operations for tax documents using Qdrant.
    """
    
    DEFAULT_COLLECTION = "tax_documents"
    DEFAULT_VECTOR_SIZE = 384  # Default for all-MiniLM-L6-v2
    
    def __init__(
        self,
        host: str = "localhost",
        port: int = 6333,
        collection_name: str = DEFAULT_COLLECTION,
        vector_size: int = DEFAULT_VECTOR_SIZE,
        embedding_model: str = "all-MiniLM-L6-v2",
    ):
        """
        Initialize the Qdrant handler.
        
        Args:
            host: Qdrant server host
            port: Qdrant server port
            collection_name: Name of the collection to use
            vector_size: Size of embedding vectors
            embedding_model: Name of sentence-transformers model
        """
        if not QDRANT_AVAILABLE:
            raise RuntimeError(
                "qdrant-client is not installed. Install with: pip install qdrant-client"
            )
        
        self.host = host
        self.port = port
        self.collection_name = collection_name
        self.vector_size = vector_size
        self.embedding_model_name = embedding_model
        
        # Initialize client
        self.client = QdrantClient(host=host, port=port)
        
        # Initialize embedding model
        self.embedding_model = None
        if EMBEDDINGS_AVAILABLE:
            try:
                self.embedding_model = SentenceTransformer(embedding_model)
                logger.info(f"Loaded embedding model: {embedding_model}")
            except Exception as e:
                logger.warning(f"Failed to load embedding model: {e}")
        
        # Create collection if it doesn't exist
        self._ensure_collection()
    
    def _ensure_collection(self) -> None:
        """Create the collection if it doesn't exist."""
        try:
            collections = self.client.get_collections()
            collection_names = [c.name for c in collections.collections]
            
            if self.collection_name not in collection_names:
                self.client.create_collection(
                    collection_name=self.collection_name,
                    vectors_config=VectorParams(
                        size=self.vector_size,
                        distance=Distance.COSINE,
                    ),
                )
                logger.info(f"Created collection: {self.collection_name}")
            else:
                logger.info(f"Collection already exists: {self.collection_name}")
        
        except Exception as e:
            logger.error(f"Failed to ensure collection: {e}")
            raise
    
    def _get_embedding(self, text: str) -> list[float]:
        """
        Generate embedding for text.
        
        Args:
            text: Text to embed
        
        Returns:
            Embedding vector
        """
        if self.embedding_model is None:
            raise RuntimeError("Embedding model not available")
        
        embedding = self.embedding_model.encode(text)
        return embedding.tolist()
    
    def store_document(
        self,
        document_id: int,
        ocr_text: str,
        document_type: DocumentType,
        tax_year: int,
        file_name: str,
        extracted_fields: Optional[dict[str, Any]] = None,
    ) -> str:
        """
        Store a document in the vector database.
        
        Args:
            document_id: Database ID of the document
            ocr_text: Full OCR text of the document
            document_type: Type of tax document
            tax_year: Tax year
            file_name: Original file name
            extracted_fields: Optional extracted field values
        
        Returns:
            Point ID in the vector database
        """
        # Generate embedding
        embedding = self._get_embedding(ocr_text)
        
        # Create point ID
        point_id = str(uuid.uuid4())
        
        # Create payload
        payload = {
            "document_id": document_id,
            "document_type": document_type.value,
            "tax_year": tax_year,
            "file_name": file_name,
            "ocr_text": ocr_text[:10000],  # Limit stored text size
            "extracted_fields": extracted_fields or {},
        }
        
        # Create point
        point = PointStruct(
            id=point_id,
            vector=embedding,
            payload=payload,
        )
        
        # Upsert to collection
        self.client.upsert(
            collection_name=self.collection_name,
            points=[point],
        )
        
        logger.info(f"Stored document {document_id} in vector database")
        return point_id
    
    def search(
        self,
        query: str,
        limit: int = 5,
        tax_year: Optional[int] = None,
        document_type: Optional[DocumentType] = None,
    ) -> list[dict]:
        """
        Search for documents similar to the query.
        
        Args:
            query: Search query text
            limit: Maximum number of results
            tax_year: Optional filter by tax year
            document_type: Optional filter by document type
        
        Returns:
            List of matching documents with scores
        """
        # Generate query embedding
        query_embedding = self._get_embedding(query)
        
        # Build filter
        filter_conditions = []
        
        if tax_year is not None:
            filter_conditions.append(
                FieldCondition(
                    key="tax_year",
                    match=MatchValue(value=tax_year),
                )
            )
        
        if document_type is not None:
            filter_conditions.append(
                FieldCondition(
                    key="document_type",
                    match=MatchValue(value=document_type.value),
                )
            )
        
        query_filter = Filter(must=filter_conditions) if filter_conditions else None
        
        # Search
        results = self.client.search(
            collection_name=self.collection_name,
            query_vector=query_embedding,
            limit=limit,
            query_filter=query_filter,
        )
        
        # Format results
        matches = []
        for result in results:
            matches.append({
                "id": result.id,
                "score": result.score,
                "document_id": result.payload.get("document_id"),
                "document_type": result.payload.get("document_type"),
                "tax_year": result.payload.get("tax_year"),
                "file_name": result.payload.get("file_name"),
                "ocr_text": result.payload.get("ocr_text", "")[:500],  # Preview
                "extracted_fields": result.payload.get("extracted_fields", {}),
            })
        
        return matches
    
    def get_document_by_id(self, document_id: int) -> Optional[dict]:
        """
        Get a document by its database ID.
        
        Args:
            document_id: Database ID of the document
        
        Returns:
            Document data or None if not found
        """
        # Search with filter
        results = self.client.scroll(
            collection_name=self.collection_name,
            scroll_filter=Filter(
                must=[
                    FieldCondition(
                        key="document_id",
                        match=MatchValue(value=document_id),
                    )
                ]
            ),
            limit=1,
        )
        
        if results[0]:
            point = results[0][0]
            return {
                "id": point.id,
                "document_id": point.payload.get("document_id"),
                "document_type": point.payload.get("document_type"),
                "tax_year": point.payload.get("tax_year"),
                "file_name": point.payload.get("file_name"),
                "ocr_text": point.payload.get("ocr_text"),
                "extracted_fields": point.payload.get("extracted_fields", {}),
            }
        
        return None
    
    def delete_document(self, document_id: int) -> bool:
        """
        Delete a document from the vector database.
        
        Args:
            document_id: Database ID of the document
        
        Returns:
            True if document was deleted
        """
        # Find the point
        results = self.client.scroll(
            collection_name=self.collection_name,
            scroll_filter=Filter(
                must=[
                    FieldCondition(
                        key="document_id",
                        match=MatchValue(value=document_id),
                    )
                ]
            ),
            limit=1,
        )
        
        if results[0]:
            point_id = results[0][0].id
            self.client.delete(
                collection_name=self.collection_name,
                points_selector=[point_id],
            )
            logger.info(f"Deleted document {document_id} from vector database")
            return True
        
        return False
    
    def get_context_for_query(
        self,
        query: str,
        tax_year: int,
        max_documents: int = 10,
    ) -> str:
        """
        Get relevant context for a query (for RAG).
        
        Args:
            query: User query
            tax_year: Tax year to search in
            max_documents: Maximum number of documents to include
        
        Returns:
            Combined context string
        """
        results = self.search(
            query=query,
            limit=max_documents,
            tax_year=tax_year,
        )
        
        if not results:
            return "No relevant documents found."
        
        context_parts = []
        for i, result in enumerate(results, 1):
            context_parts.append(
                f"Document {i}: {result['document_type']} - {result['file_name']}\n"
                f"Relevance: {result['score']:.2f}\n"
                f"Content preview: {result['ocr_text']}\n"
            )
        
        return "\n---\n".join(context_parts)
    
    def check_connection(self) -> bool:
        """
        Check if Qdrant is running and accessible.
        
        Returns:
            True if connection is successful
        """
        try:
            self.client.get_collections()
            return True
        except Exception as e:
            logger.error(f"Failed to connect to Qdrant: {e}")
            return False
    
    def get_collection_info(self) -> dict:
        """
        Get information about the collection.
        
        Returns:
            Dictionary with collection info
        """
        try:
            info = self.client.get_collection(self.collection_name)
            return {
                "name": self.collection_name,
                "points_count": info.points_count,
                "vectors_count": info.vectors_count,
                "status": info.status.value,
            }
        except Exception as e:
            logger.error(f"Failed to get collection info: {e}")
            return {"error": str(e)}