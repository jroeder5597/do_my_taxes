"""
Tax filing assistant module.
Provides interactive assistance for tax filing using LLM and extracted data.
"""

import os
import time
from decimal import Decimal
from pathlib import Path
from typing import Optional, Set

from rich.console import Console
from rich.panel import Panel
from rich.prompt import Prompt
from rich.table import Table
from rich import print as rprint

from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler, FileCreatedEvent

from src.storage import SQLiteHandler, QdrantHandler, DocumentType, ProcessingStatus
from src.extraction import LLMExtractor, DataValidator
from src.extraction.prompts import PromptTemplates
from src.utils import get_logger, ensure_dir, get_file_hash, list_documents
from src.utils.config import get_settings
from src.ocr.pdfplumber_tax_extractor import PDFPlumberTaxExtractor

logger = get_logger(__name__)

# Try to import screen reader
try:
    from .screen_reader import ScreenReader
    SCREEN_READER_AVAILABLE = True
except ImportError:
    SCREEN_READER_AVAILABLE = False
    logger.warning("Screen reader not available.")

# Try to import tax guidance
try:
    from .tax_guidance import TaxGuidanceLoader, auto_load_tax_guidance
    TAX_GUIDANCE_AVAILABLE = True
except ImportError:
    TAX_GUIDANCE_AVAILABLE = False
    auto_load_tax_guidance = None
    logger.debug("Tax guidance module not available.")

# Try to import web search
try:
    from src.web import WebSearchClient, PIIDetectionError, create_search_client
    WEB_SEARCH_AVAILABLE = True
except ImportError:
    WEB_SEARCH_AVAILABLE = False
    WebSearchClient = None
    PIIDetectionError = Exception
    create_search_client = None
    logger.debug("Web search module not available.")

# Try to import Chrome reader
try:
    from .chrome_reader import ChromeReader, read_tax_software_if_available, is_chrome_running
    CHROME_READER_AVAILABLE = True
except ImportError:
    CHROME_READER_AVAILABLE = False
    ChromeReader = None
    read_tax_software_if_available = None
    is_chrome_running = None
    logger.debug("Chrome reader module not available.")


class DocumentFileHandler(FileSystemEventHandler):
    """Handler for file system events to detect new documents."""
    
    def __init__(self, callback, extensions: Set[str] = None):
        super().__init__()
        self.callback = callback
        self.extensions = extensions or {'.pdf', '.png', '.jpg', '.jpeg', '.tiff', '.tif'}
        self._processed_paths: Set[str] = set()
    
    def on_created(self, event):
        if event.is_directory:
            return
        
        if isinstance(event, FileCreatedEvent):
            path = event.src_path
            ext = Path(path).suffix.lower()
            
            if ext in self.extensions and path not in self._processed_paths:
                self._processed_paths.add(path)
                logger.info(f"New document detected: {path}")
                self.callback(path)


class FileWatcher:
    """File watcher that monitors a directory for new documents."""
    
    def __init__(self, watch_path: str, callback, extensions: Set[str] = None):
        self.watch_path = Path(watch_path)
        self.callback = callback
        self.extensions = extensions or {'.pdf', '.png', '.jpg', '.jpeg', '.tiff', '.tif'}
        self.observer = Observer()
        self.event_handler = DocumentFileHandler(self._on_new_file, self.extensions)
    
    def _on_new_file(self, path: str):
        """Callback when a new file is detected."""
        try:
            self.callback(path)
        except Exception as e:
            logger.error(f"Error processing new file {path}: {e}")
    
    def start(self):
        """Start watching the directory."""
        if not self.watch_path.exists():
            logger.warning(f"Watch path does not exist: {self.watch_path}")
            self.watch_path.mkdir(parents=True, exist_ok=True)
        
        self.observer.schedule(
            self.event_handler,
            str(self.watch_path),
            recursive=True
        )
        self.observer.start()
        logger.info(f"File watcher started for: {self.watch_path}")
    
    def stop(self):
        """Stop watching the directory."""
        self.observer.stop()
        self.observer.join()
        logger.info("File watcher stopped")


class TaxAssistant:
    """
    Interactive tax filing assistant.
    Helps users fill out tax forms using extracted data and LLM guidance.
    """
    
    def __init__(self, tax_year: int, auto_load_guidance: bool = True, auto_start_services: bool = True):
        """
        Initialize the tax assistant.
        
        Args:
            tax_year: Tax year to assist with
            auto_load_guidance: Automatically load tax guidance if directories exist
            auto_start_services: Automatically start OCR, Qdrant, Ollama services
        """
        self.tax_year = tax_year
        self.console = Console()
        
        # Auto-start services if enabled
        self._services_status = {}
        if auto_start_services:
            try:
                from src.utils.service_manager import ensure_services
                self._services_status = ensure_services(self.console)
            except Exception as e:
                logger.debug(f"Auto-start services failed: {e}")
        
        # Now initialize other components
        self.db = SQLiteHandler()
        settings = get_settings()
        self.llm = LLMExtractor(
            provider=settings.llm.provider,
            temperature=0.3,
        )
        self.pdfplumber_tax = PDFPlumberTaxExtractor()
        self.qdrant: Optional[QdrantHandler] = None
        self.screen_reader: Optional[ScreenReader] = None
        self.web_search_client: Optional[WebSearchClient] = None
        
        # Initialize web search client if available
        if WEB_SEARCH_AVAILABLE and create_search_client:
            try:
                self.web_search_client = create_search_client()
                if self.web_search_client:
                    logger.info("Web search client initialized")
            except Exception as e:
                logger.debug(f"Could not initialize web search client: {e}")
        
        # Conversation history
        self.conversation_history: list[dict] = []
        
        # Auto-load tax guidance if enabled and directories exist
        self._guidance_loaded = False
        if auto_load_guidance and TAX_GUIDANCE_AVAILABLE and auto_load_tax_guidance:
            try:
                from pathlib import Path
                results = auto_load_tax_guidance(tax_year)
                if results:
                    total_chunks = sum(results.values())
                    if total_chunks > 0:
                        self._guidance_loaded = True
                        self.console.print(f"[green][OK] Tax guidance loaded: {total_chunks} chunks[/green]")
            except Exception as e:
                logger.debug(f"Auto-load guidance failed: {e}")
        
        # Auto-process documents in the data directory
        self._auto_process_documents()
        
        # Start file watcher for new documents
        self._file_watcher: Optional[FileWatcher] = None
        self._start_file_watcher()
        
        # Initialize system prompt
        self._init_conversation()
    
    def _start_file_watcher(self):
        """Start watching for new files in the data directory."""
        try:
            settings = get_settings()
            data_dir = Path(settings.paths.raw_documents)
            
            def on_new_file(file_path: str):
                self._process_new_file(file_path)
            
            self._file_watcher = FileWatcher(str(data_dir), on_new_file)
            self._file_watcher.start()
        except Exception as e:
            logger.debug(f"Could not start file watcher: {e}")
    
    def _stop_file_watcher(self):
        """Stop the file watcher."""
        if self._file_watcher:
            try:
                self._file_watcher.stop()
            except Exception as e:
                logger.debug(f"Error stopping file watcher: {e}")
    
    def _process_new_file(self, file_path: str):
        """Process a newly detected file."""
        path = Path(file_path)
        
        try:
            tax_year = self.db.get_or_create_tax_year(self.tax_year)
            file_hash = get_file_hash(path)
            
            if self.db.document_exists_by_hash(tax_year.id, file_hash):
                return
            
            self.console.print(f"[blue]New document detected: {path.name}[/blue]")
            
            from src.ocr import PDFProcessor, DocumentClassifier
            
            pdf_processor = PDFProcessor()
            classifier = DocumentClassifier()
            validator = DataValidator(self.tax_year)
            
            doc = self.db.create_document(
                tax_year_id=tax_year.id,
                document_type=DocumentType.UNKNOWN,
                file_name=path.name,
                file_path=str(path),
                file_hash=file_hash,
            )
            
            self.db.update_document_status(doc.id, ProcessingStatus.PROCESSING)
            
            if path.suffix.lower() == ".pdf":
                text = pdf_processor.extract_text(path)
            else:
                text = ""
            
            self.db.update_document_ocr_text(doc.id, text)
            
            doc_type, confidence = classifier.classify(text)
            self.db.update_document_type(doc.id, doc_type)
            
            extraction_success = False
            
            if doc_type == DocumentType.W2:
                data = self._extract_w2_via_pdfplumber_tax(path, doc.id)
                if data:
                    is_valid, errors = validator.validate_w2(data)
                    if is_valid:
                        self.db.save_w2_data(data)
                        self.console.print(f"[green][OK] Extracted W-2 data from {path.name}[/green]")
                        extraction_success = True
                    else:
                        self.console.print(f"[red]W-2 validation failed: {errors}[/red]")
            
            elif doc_type == DocumentType.FORM_1099_INT:
                data = self._extract_1099_int_via_pdfplumber_tax(path, doc.id)
                if data:
                    self.db.save_1099_int_data(data)
                    self.console.print(f"[green][OK] Extracted 1099-INT data from {path.name}[/green]")
                    extraction_success = True
            
            elif doc_type == DocumentType.FORM_1099_DIV:
                data = self._extract_1099_div_via_pdfplumber_tax(path, doc.id)
                if data:
                    self.db.save_1099_div_data(data)
                    self.console.print(f"[green][OK] Extracted 1099-DIV data from {path.name}[/green]")
                    extraction_success = True
            
            else:
                extraction_success = True
            
            if extraction_success:
                self.db.update_document_status(doc.id, ProcessingStatus.VALIDATED)
            else:
                self.db.update_document_status(doc.id, ProcessingStatus.ERROR)
                
        except Exception as e:
            logger.error(f"Error processing new file {path.name}: {e}")
            self.console.print(f"[red]Error processing {path.name}: {e}[/red]")
    
    def _extract_w2_via_pdfplumber_tax(self, file_path, document_id: int):
        from decimal import Decimal
        from src.storage.models import W2Data
        
        extracted = self.pdfplumber_tax.extract_w2_from_file(str(file_path))
        if not extracted or not extracted.get('wages_tips_compensation'):
            return None
        
        def to_decimal(val, default='0'):
            if val is None:
                return Decimal(default)
            return Decimal(str(val).replace(',', ''))
        
        return W2Data(
            document_id=document_id,
            employer_ein=extracted.get('employer_ein'),
            employer_name=extracted.get('employer_name', ''),
            employer_address=extracted.get('employer_address'),
            employer_city=extracted.get('employer_city'),
            employer_state=extracted.get('employer_state'),
            employer_zip=extracted.get('employer_zip'),
            employee_name=extracted.get('employee_name', ''),
            employee_ssn=extracted.get('employee_ssn'),
            employee_address=extracted.get('employee_address'),
            employee_city=extracted.get('employee_city'),
            employee_state=extracted.get('employee_state'),
            employee_zip=extracted.get('employee_zip'),
            wages_tips_compensation=to_decimal(extracted.get('wages_tips_compensation')),
            federal_income_tax_withheld=to_decimal(extracted.get('federal_income_tax_withheld')),
            social_security_wages=to_decimal(extracted.get('social_security_wages')),
            social_security_tax_withheld=to_decimal(extracted.get('social_security_tax_withheld')),
            medicare_wages=to_decimal(extracted.get('medicare_wages')),
            medicare_tax_withheld=to_decimal(extracted.get('medicare_tax_withheld')),
            state_wages_tips=to_decimal(extracted['state_wages_tips']) if extracted.get('state_wages_tips') else None,
            state_income_tax=to_decimal(extracted['state_income_tax']) if extracted.get('state_income_tax') else None,
            raw_data=extracted,
        )
    
    def _extract_1099_int_via_pdfplumber_tax(self, file_path, document_id: int):
        from decimal import Decimal
        from src.storage.models import Form1099INT
        
        extracted = self.pdfplumber_tax.extract_1099_int_from_file(str(file_path))
        if not extracted or not extracted.get('interest_income'):
            return None
        
        def to_decimal(val, default='0'):
            if val is None:
                return Decimal(default)
            return Decimal(str(val).replace(',', ''))
        
        return Form1099INT(
            document_id=document_id,
            payer_name=extracted.get('payer_name', 'Unknown Payer'),
            payer_tin=extracted.get('payer_ein'),
            recipient_name=extracted.get('recipient_name', 'Unknown Recipient'),
            recipient_tin=extracted.get('recipient_ssn'),
            interest_income=to_decimal(extracted.get('interest_income')),
            tax_exempt_interest=to_decimal(extracted.get('tax_exempt_interest', '0')),
            federal_income_tax_withheld=to_decimal(extracted.get('federal_tax_withheld', '0')),
            foreign_tax_paid=to_decimal(extracted.get('foreign_tax_paid', '0')),
            raw_data=extracted,
        )
    
    def _extract_1099_div_via_pdfplumber_tax(self, file_path, document_id: int):
        from decimal import Decimal
        from src.storage.models import Form1099DIV
        
        extracted = self.pdfplumber_tax.extract_1099_div_from_file(str(file_path))
        if not extracted or not extracted.get('total_ordinary_dividends'):
            return None
        
        def to_decimal(val, default='0'):
            if val is None:
                return Decimal(default)
            return Decimal(str(val).replace(',', ''))
        
        return Form1099DIV(
            document_id=document_id,
            payer_name=extracted.get('payer_name', 'Unknown Payer') or 'Unknown Payer',
            payer_tin=extracted.get('payer_ein'),
            recipient_name=extracted.get('recipient_name') or 'Unknown Recipient',
            recipient_tin=extracted.get('recipient_ssn'),
            total_ordinary_dividends=to_decimal(extracted.get('total_ordinary_dividends')),
            qualified_dividends=to_decimal(extracted.get('qualified_dividends', '0')),
            section_199a_dividends=to_decimal(extracted.get('section_199a_dividends', '0')),
            federal_income_tax_withheld=to_decimal(extracted.get('federal_tax_withheld', '0')),
            foreign_tax_paid=to_decimal(extracted.get('foreign_tax_paid', '0')),
            raw_data=extracted,
        )
    
    def _init_conversation(self) -> None:
        """Initialize the conversation with system prompt."""
        # Get enhanced system prompt with current tax year info
        system_prompt = self._get_enhanced_system_prompt()
        
        self.conversation_history = [
            {"role": "system", "content": system_prompt}
        ]
        
        # Add context about user's tax data
        context = self._build_user_context()
        if context:
            self.conversation_history.append({
                "role": "system",
                "content": f"Here is the user's tax data context:\n\n{context}"
            })
    
    def _auto_process_documents(self) -> None:
        from pathlib import Path
        from src.ocr import PDFProcessor, DocumentClassifier
        
        settings = get_settings()
        data_dir = Path(settings.paths.raw_documents)
        
        if not data_dir.exists():
            ensure_dir(data_dir)
            return
        
        files = list(list_documents(data_dir, recursive=True))
        
        if not files:
            return
        
        tax_year = self.db.get_or_create_tax_year(self.tax_year)
        
        guidance_keywords = ['booklet', 'instructions', 'summary', 'guidance']
        unprocessed_files = []
        
        for file_path in files:
            if any(keyword in file_path.name.lower() for keyword in guidance_keywords):
                continue
            if 'guidance' in str(file_path).lower():
                continue
            file_hash = get_file_hash(file_path)
            if not self.db.document_exists_by_hash(tax_year.id, file_hash):
                unprocessed_files.append(file_path)
        
        existing_docs = self.db.list_documents(tax_year_id=tax_year.id)
        for doc in existing_docs:
            if doc.processing_status in [ProcessingStatus.PENDING, ProcessingStatus.ERROR]:
                if doc.file_path:
                    file_path = Path(doc.file_path)
                    if file_path.exists():
                        unprocessed_files.append(file_path)
        
        if not unprocessed_files:
            return
        
        self.console.print(f"[blue]Found {len(unprocessed_files)} new document(s) to process...[/blue]")
        
        pdf_processor = PDFProcessor()
        classifier = DocumentClassifier()
        validator = DataValidator(self.tax_year)
        
        processed_count = 0
        for file_path in unprocessed_files:
            try:
                file_hash = get_file_hash(file_path)
                doc = self.db.create_document(
                    tax_year_id=tax_year.id,
                    document_type=DocumentType.UNKNOWN,
                    file_name=file_path.name,
                    file_path=str(file_path),
                    file_hash=file_hash,
                )
                
                self.db.update_document_status(doc.id, ProcessingStatus.PROCESSING)
                
                if file_path.suffix.lower() == ".pdf":
                    text = pdf_processor.extract_text(file_path)
                else:
                    text = ""
                
                self.db.update_document_ocr_text(doc.id, text)
                
                doc_type, confidence = classifier.classify(text)
                self.db.update_document_type(doc.id, doc_type)
                
                extraction_success = False
                if doc_type == DocumentType.W2:
                    data = self._extract_w2_via_pdfplumber_tax(file_path, doc.id)
                    if data:
                        is_valid, errors = validator.validate_w2(data)
                        if is_valid:
                            self.db.save_w2_data(data)
                            processed_count += 1
                            extraction_success = True
                        else:
                            error_msg = f"W2 validation failed: {errors}"
                            logger.warning(error_msg)
                            self.db.update_document_status(doc.id, ProcessingStatus.ERROR, error_msg)
                    else:
                        error_msg = "W2 extraction returned no data"
                        logger.warning(error_msg)
                        self.db.update_document_status(doc.id, ProcessingStatus.ERROR, error_msg)
                
                elif doc_type == DocumentType.FORM_1099_INT:
                    data = self._extract_1099_int_via_pdfplumber_tax(file_path, doc.id)
                    if data:
                        self.db.save_1099_int_data(data)
                        processed_count += 1
                        extraction_success = True
                    else:
                        error_msg = "1099-INT extraction returned no data"
                        logger.warning(error_msg)
                        self.db.update_document_status(doc.id, ProcessingStatus.ERROR, error_msg)
                
                elif doc_type == DocumentType.FORM_1099_DIV:
                    data = self._extract_1099_div_via_pdfplumber_tax(file_path, doc.id)
                    if data:
                        self.db.save_1099_div_data(data)
                        processed_count += 1
                        extraction_success = True
                    else:
                        error_msg = "1099-DIV extraction returned no data"
                        logger.warning(error_msg)
                        self.db.update_document_status(doc.id, ProcessingStatus.ERROR, error_msg)
                
                if extraction_success:
                    self.db.update_document_status(doc.id, ProcessingStatus.VALIDATED)
                elif doc_type not in [DocumentType.W2, DocumentType.FORM_1099_INT, DocumentType.FORM_1099_DIV]:
                    self.db.update_document_status(doc.id, ProcessingStatus.VALIDATED)
                
            except Exception as e:
                logger.error(f"Failed to process {file_path.name}: {e}")
                if doc:
                    self.db.update_document_status(doc.id, ProcessingStatus.ERROR)
        
        if processed_count > 0:
            self.console.print(f"[green][OK] Processed {processed_count} document(s)[/green]")
    
    def _get_enhanced_system_prompt(self) -> str:
        """Get system prompt enhanced with tax filing guidance."""
        base_prompt = PromptTemplates.get_assistant_system_prompt()
        
        # Add tax year specific guidance
        guidance_context = self._get_tax_guidance_context()
        if guidance_context:
            return f"{base_prompt}\n\n{guidance_context}"
        
        return base_prompt
    
    def _get_tax_guidance_context(self) -> str:
        """Get relevant tax guidance context for the tax year."""
        if not TAX_GUIDANCE_AVAILABLE:
            return ""
        
        try:
            loader = TaxGuidanceLoader()
            
            # Get general guidance for the tax year
            guidance = loader.get_context_for_query(
                query="tax filing requirements forms schedules",
                tax_year=self.tax_year,
                jurisdiction=None,  # Get all jurisdictions
                max_chunks=5,
            )
            
            return guidance
        except Exception as e:
            logger.debug(f"Could not load tax guidance: {e}")
            return ""
    
    def _build_user_context(self) -> str:
        """Build context string from user's extracted tax data."""
        tax_year = self.db.get_tax_year(self.tax_year)
        
        if not tax_year:
            return ""
        
        context_parts = []
        
        # Get summary
        summary = self.db.get_tax_summary(tax_year.id)
        
        context_parts.append(f"Tax Year: {self.tax_year}")
        context_parts.append(f"Total Wages: ${summary['total_wages']:,.2f}")
        context_parts.append(f"Total Interest Income: ${summary['total_interest']:,.2f}")
        context_parts.append(f"Total Dividends: ${summary['total_dividends']:,.2f}")
        context_parts.append(f"Total Federal Tax Withheld: ${summary['total_federal_withheld']:,.2f}")
        context_parts.append(f"Total State Tax Withheld: ${summary['total_state_withheld']:,.2f}")
        
        # Add W-2 details
        w2_list = self.db.list_w2_data(tax_year.id)
        if w2_list:
            context_parts.append("\nW-2 Forms:")
            for w2 in w2_list:
                context_parts.append(f"  - Employer: {w2.employer_name}")
                context_parts.append(f"    Wages: ${w2.wages_tips_compensation:,.2f}")
                context_parts.append(f"    Federal Withheld: ${w2.federal_income_tax_withheld:,.2f}")
        
        # Add 1099-INT details
        int_list = self.db.list_1099_int_data(tax_year.id)
        if int_list:
            context_parts.append("\n1099-INT Forms:")
            for form in int_list:
                context_parts.append(f"  - Payer: {form.payer_name}")
                context_parts.append(f"    Interest: ${form.interest_income:,.2f}")
        
        # Add 1099-DIV details
        div_list = self.db.list_1099_div_data(tax_year.id)
        if div_list:
            context_parts.append("\n1099-DIV Forms:")
            for form in div_list:
                context_parts.append(f"  - Payer: {form.payer_name}")
                context_parts.append(f"    Dividends: ${form.total_ordinary_dividends:,.2f}")
        
        return "\n".join(context_parts)
    
    def _build_context_for_page(self, page_content: str) -> str:
        """
        Build context string filtered to match page content keywords.
        Only loads document data relevant to what's on the current page.
        Loads ALL fields for a detected document type.
        """
        tax_year = self.db.get_tax_year(self.tax_year)
        
        if not tax_year:
            return ""
        
        page_lower = page_content.lower()
        context_parts = []
        context_parts.append(f"Tax Year: {self.tax_year}")
        
        # Detect which document types are mentioned on the page
        has_w2 = any(kw in page_lower for kw in ['w-2', 'w2 ', 'wage', 'employer', 'salary'])
        has_int = any(kw in page_lower for kw in ['1099-int', '1099 int', 'interest income'])
        has_div = any(kw in page_lower for kw in ['1099-div', '1099 div', 'dividend'])
        
        # If no specific match, check for generic income terms
        if not (has_w2 or has_int or has_div):
            if 'income' in page_lower:
                has_w2 = has_int = has_div = True
        
        # Load ALL W-2 data if relevant
        if has_w2:
            w2_list = self.db.list_w2_data(tax_year.id)
            if w2_list:
                context_parts.append("\nW-2 Forms:")
                for w2 in w2_list:
                    context_parts.append(f"  - Employer: {w2.employer_name}")
                    context_parts.append(f"    Employer EIN: {w2.employer_ein or 'N/A'}")
                    context_parts.append(f"    Wages (Box 1): ${w2.wages_tips_compensation:,.2f}")
                    context_parts.append(f"    Federal Tax Withheld (Box 2): ${w2.federal_income_tax_withheld:,.2f}")
                    context_parts.append(f"    Social Security Wages (Box 3): ${w2.social_security_wages:,.2f}")
                    context_parts.append(f"    Social Security Tax Withheld (Box 4): ${w2.social_security_tax_withheld:,.2f}")
                    context_parts.append(f"    Medicare Wages (Box 5): ${w2.medicare_wages:,.2f}")
                    context_parts.append(f"    Medicare Tax Withheld (Box 6): ${w2.medicare_tax_withheld:,.2f}")
        
        # Load ALL 1099-INT data if relevant
        if has_int:
            int_list = self.db.list_1099_int_data(tax_year.id)
            if int_list:
                context_parts.append("\n1099-INT Forms:")
                for form in int_list:
                    context_parts.append(f"  - Payer: {form.payer_name}")
                    context_parts.append(f"    Payer TIN: {form.payer_tin or 'N/A'}")
                    context_parts.append(f"    Interest Income (Box 1): ${form.interest_income:,.2f}")
        
        # Load ALL 1099-DIV data if relevant
        if has_div:
            div_list = self.db.list_1099_div_data(tax_year.id)
            if div_list:
                context_parts.append("\n1099-DIV Forms:")
                for form in div_list:
                    context_parts.append(f"  - Payer: {form.payer_name}")
                    context_parts.append(f"    Payer TIN: {form.payer_tin or 'N/A'}")
                    context_parts.append(f"    Total Ordinary Dividends (Box 1a): ${form.total_ordinary_dividends or 0:,.2f}")
                    context_parts.append(f"    Qualified Dividends (Box 1b): ${form.qualified_dividends or 0:,.2f}")
                    context_parts.append(f"    Total Capital Gain (Box 2a): ${form.total_capital_gain or 0:,.2f}")
        
        if len(context_parts) == 1:
            return "No relevant documents for this page."
        
        return "\n".join(context_parts)
    
    def chat(self, message: str) -> str:
        """
        Send a message to the assistant and get a response.
        
        Args:
            message: User message
            
        Returns:
            Assistant response
        """
        # Always include user's tax data context for relevant queries
        user_context = self._build_user_context()
        user_data_context = ""
        if user_context:
            user_data_context = f"\n\nUser's tax data for reference:\n{user_context}"
        
        # Try to read content from Chrome if tax software is open
        chrome_context = ""
        if CHROME_READER_AVAILABLE and read_tax_software_if_available:
            try:
                chrome_content = read_tax_software_if_available()
                if chrome_content:
                    chrome_context = f"\n\nContent from user's tax software browser page:\n{chrome_content}"
            except Exception as e:
                logger.debug(f"Could not read Chrome tax software: {e}")
        
        # Retrieve relevant tax guidance for this query
        guidance_context = self._retrieve_tax_guidance(message)
        
        # Build message with user data, Chrome content, and guidance context
        context_parts = []
        if user_data_context:
            context_parts.append(user_data_context)
        if chrome_context:
            context_parts.append(chrome_context)
        if guidance_context:
            context_parts.append(guidance_context)
        
        if context_parts:
            enhanced_message = message + "\n" + "\n".join(context_parts)
        else:
            enhanced_message = message
        
        # Add user message to history
        self.conversation_history.append({"role": "user", "content": enhanced_message})
        
        # Get response from LLM
        response = self.llm.chat(self.conversation_history)
        
        # Add response to history (use original message, not enhanced)
        # Replace the last user message with original
        self.conversation_history[-2] = {"role": "user", "content": message}
        self.conversation_history.append({"role": "assistant", "content": response})
        
        return response
    
    def _retrieve_tax_guidance(self, query: str) -> str:
        """
        Retrieve relevant tax guidance for a query.
        
        Uses a fallback strategy:
        1. First, search local tax guidance documents via Qdrant
        2. If local guidance is insufficient, fall back to web search
           (with STRICT PII protection - no personal info is ever sent)
        
        Args:
            query: User's tax-related query
            
        Returns:
            Context string for the LLM
        """
        context_parts = []
        
        # Step 1: Try local tax guidance first
        if TAX_GUIDANCE_AVAILABLE:
            try:
                loader = TaxGuidanceLoader()
                
                # Determine jurisdiction from query
                jurisdiction = None
                query_lower = query.lower()
                if any(term in query_lower for term in ["california", " ca ", " ca state"]):
                    jurisdiction = "ca"
                elif any(term in query_lower for term in ["arizona", " az ", " az state"]):
                    jurisdiction = "az"
                elif any(term in query_lower for term in ["federal", "irs", "form 1040"]):
                    jurisdiction = "federal"
                
                # Get relevant guidance
                guidance = loader.get_context_for_query(
                    query=query,
                    tax_year=self.tax_year,
                    jurisdiction=jurisdiction,
                    max_chunks=3,
                )
                
                if guidance:
                    context_parts.append("From local tax guidance documents:")
                    context_parts.append(guidance)
            except Exception as e:
                logger.debug(f"Could not retrieve local tax guidance: {e}")
        
        # Step 2: Fall back to web search if local guidance is insufficient
        # IMPORTANT: Web search has STRICT PII protection
        # No personal information (names, SSN, employers, etc.) is ever sent
        if self.web_search_client and len(context_parts) == 0:
            try:
                # Determine jurisdiction for web search context
                jurisdiction = None
                query_lower = query.lower()
                if any(term in query_lower for term in ["california", " ca ", " ca state"]):
                    jurisdiction = "ca"
                elif any(term in query_lower for term in ["arizona", " az ", " az state"]):
                    jurisdiction = "az"
                elif any(term in query_lower for term in ["federal", "irs", "form 1040"]):
                    jurisdiction = "federal"
                
                # Attempt web search (will raise PIIDetectionError if PII detected)
                results = self.web_search_client.search_tax_guidance(
                    query=query,
                    tax_year=self.tax_year,
                    jurisdiction=jurisdiction,
                )
                
                if results:
                    context_parts.append("From web search (general tax guidance):")
                    for i, result in enumerate(results[:3], 1):
                        context_parts.append(f"\n{i}. {result.title}")
                        context_parts.append(f"   {result.content[:500]}...")
                        context_parts.append(f"   Source: {result.url}")
                    
            except PIIDetectionError as e:
                # PII was detected - search was blocked for privacy
                logger.warning(f"Web search blocked due to PII detection: {e}")
                context_parts.append(
                    "[WARNING] Web search was blocked because the query contained "
                    "personal information. For your privacy, no personal data is ever "
                    "sent to external search engines. Please rephrase your question "
                    "using only general terms (e.g., 'What are the 2025 federal tax brackets?' "
                    "instead of 'What are my tax brackets for $75,000 salary?')"
                )
            except Exception as e:
                logger.debug(f"Web search failed: {e}")
        
        return "\n".join(context_parts)
    
    def run_interactive(self) -> None:
        """Run the interactive assistant session."""
        # Try to launch Chrome with remote debugging if not already running
        chrome_available = False
        if CHROME_READER_AVAILABLE:
            from .chrome_reader import ensure_chrome_running, is_chrome_running
            if not is_chrome_running():
                ensure_chrome_running(self.console)
            chrome_available = is_chrome_running()
        
        # Build status message
        status_parts = [f"Tax Year: {self.tax_year}"]
        if self._guidance_loaded:
            status_parts.append("[green][OK] Tax guidance loaded[/green]")
        
        # Add services status
        services = []
        if self._services_status.get("pdfplumber_tax"):
            services.append("[green]PDFPlumber Tax[/green]")
        if self._services_status.get("qdrant"):
            services.append("[green]Qdrant[/green]")
        if self._services_status.get("ollama"):
            services.append("[green]Ollama[/green]")
        if self._services_status.get("searxng"):
            services.append("[green]SearXNG[/green]")
        if chrome_available:
            services.append("[green]Chrome (Tax Software)[/green]")
        
        if services:
            status_parts.append("Services: " + ", ".join(services))
        
        self.console.print(Panel(
            f"[bold blue]Tax Filing Assistant[/bold blue]\n"
            + "\n".join(status_parts) + "\n\n"
            "Commands:\n"
            "  [cyan]watch[/cyan] - Monitor tax software and offer suggestions\n"
            "  [cyan]analyze[/cyan] - Analyze current Chrome page now\n"
            "  [cyan]summary[/cyan] - Show tax data summary\n"
            "  [cyan]forms[/cyan] - List available forms\n"
            "  [cyan]details[/cyan] - Show extracted document fields\n"
            "  [cyan]help[/cyan] - Show available commands\n"
            "  [cyan]quit[/cyan] - Exit the assistant\n\n"
            "[dim]File watcher active - new files in data/ are auto-processed[/dim]",
            title="Welcome",
        ))
        
        while True:
            try:
                user_input = Prompt.ask("\n[bold green]You[/bold green]").strip()
                
                if not user_input:
                    continue
                
                # Handle commands
                if user_input.lower() in ["quit", "exit", "q"]:
                    self._stop_file_watcher()
                    self.console.print("[yellow]Goodbye![/yellow]")
                    break
                
                elif user_input.lower() == "watch":
                    self._handle_watch()
                    continue
                
                elif user_input.lower() == "analyze":
                    self._handle_analyze()
                    continue
                
                elif user_input.lower() == "summary":
                    self._show_summary()
                    continue
                
                elif user_input.lower() == "forms":
                    self._show_forms()
                    continue
                
                elif user_input.lower() == "details":
                    self._show_document_details()
                    continue
                
                elif user_input.lower() == "help":
                    self._show_help()
                    continue
                
                elif user_input.lower() == "clear":
                    self._init_conversation()
                    self.console.print("[green]Conversation cleared.[/green]")
                    continue
                
                # Send to LLM
                with self.console.status("[bold blue]Thinking...[/bold blue]"):
                    response = self.chat(user_input)
                
                self.console.print(f"\n[bold blue]Assistant:[/bold blue]\n{response}")
             
            except KeyboardInterrupt:
                self._stop_file_watcher()
                self.console.print("\n[yellow]Goodbye![/yellow]")
                break
            
            except Exception as e:
                self.console.print(f"[red]Error: {e}[/red]")
                logger.error(f"Error in interactive session: {e}")
    
    def _handle_analyze(self) -> None:
        """Analyze current Chrome page."""
        if not CHROME_READER_AVAILABLE:
            self.console.print("[red]Chrome reader not available. Install playwright.[/red]")
            return
        
        try:
            from .chrome_reader import ChromeReader, is_chrome_running, launch_chrome_with_debugging
            
            if not is_chrome_running():
                self.console.print("[blue]Chrome not running. Launching...[/blue]")
                if not launch_chrome_with_debugging():
                    self.console.print("[red]Failed to launch Chrome.[/red]")
                    self.console.print("[yellow]Please manually launch Chrome with: chrome --remote-debugging-port=9222[/yellow]")
                    return
                self.console.print("[green]Chrome launched![/green]")
                self.console.print("[yellow]Please sign into your tax software (TaxAct, TurboTax, etc.)[/yellow]")
                return
            
            self.console.print("[blue]Reading tax software from Chrome...[/blue]")
            
            with ChromeReader() as reader:
                content = reader.read_tax_software_content()
                
                if not content:
                    self.console.print("[yellow]No tax software page found open.[/yellow]")
                    self.console.print("[yellow]Please open TaxAct, TurboTax, or H&R Block in Chrome.[/yellow]")
                    return
                
                self.console.print("[green]Found tax software page![/green]")
                
                # Get assistance from LLM with filtered context
                context = self._build_context_for_page(content)
                prompt = PromptTemplates.get_taxact_assistant_prompt(content, context)
                
                with self.console.status("[bold blue]Analyzing...[/bold blue]"):
                    response = self.llm.chat([
                        {"role": "system", "content": PromptTemplates.get_assistant_system_prompt()},
                        {"role": "user", "content": prompt},
                    ])
                
                self.console.print(f"\n[bold blue]Tax Software Analysis:[/bold blue]\n{response}")
        
        except Exception as e:
            self.console.print(f"[red]Error reading Chrome: {e}[/red]")
            logger.error(f"Chrome read error: {e}")
    
    def _handle_watch(self) -> None:
        """Handle watch mode - continuously monitor tax software and offer suggestions."""
        if not CHROME_READER_AVAILABLE:
            self.console.print("[red]Chrome reader not available. Install playwright.[/red]")
            return
        
        try:
            from .chrome_reader import ChromeReader, is_chrome_running, launch_chrome_with_debugging
            import time
            
            if not is_chrome_running():
                self.console.print("[blue]Chrome not running. Launching...[/blue]")
                if not launch_chrome_with_debugging():
                    self.console.print("[red]Failed to launch Chrome.[/red]")
                    return
                self.console.print("[green]Chrome launched![/green]")
                self.console.print("[yellow]Please sign into your tax software.[/yellow]")
                return
            
            self.console.print("[bold blue]Starting watch mode...[/bold blue]")
            self.console.print("[yellow]Press Ctrl+C to stop watching[/yellow]\n")
            
            last_content_preview = None
            watch_count = 0
            content_to_analyze = None
            
            with ChromeReader() as reader:
                watching = True
                while watching:
                    with self.console.status("[bold blue]Watching...[/bold blue]"):
                        try:
                            while True:
                                # Quick check: get preview of page content to detect changes
                                tax_tabs = reader.get_tax_software_tabs()
                                
                                if not tax_tabs:
                                    last_content_preview = None
                                    time.sleep(3)
                                    continue
                                
                                page = tax_tabs[0].get("page")
                                if not page:
                                    time.sleep(3)
                                    continue
                                
                                # Get TaxAct-specific signals to detect SPA page changes
                                try:
                                    change_signals = page.evaluate("""
                                        () => {
                                            const h1 = document.querySelector('h1')?.innerText || '';
                                            const question = document.querySelector('[class*="question"], [class*="prompt"], .question-text')?.innerText || '';
                                            const formLabels = Array.from(document.querySelectorAll('label, .field-label')).slice(0,3).map(l => l.innerText).join('|');
                                            const step = document.querySelector('[class*="step"][class*="active"], [class*="current-step"]')?.innerText || '';
                                            return JSON.stringify({h1, question, formLabels, step});
                                        }
                                    """) or ""
                                except:
                                    change_signals = ""
                                
                                page_changed = (change_signals != last_content_preview)
                                last_content_preview = change_signals
                                
                                if page_changed:
                                    content_to_analyze = reader.read_tax_software_content()
                                    if content_to_analyze:
                                        watch_count += 1
                                        break  # Exit status context to print response
                                
                                # Wait before next check
                                time.sleep(3)
                        
                        except KeyboardInterrupt:
                            watching = False
                            break
                    
                    # Print response outside status context
                    if content_to_analyze:
                        self.console.print(f"\n[bold green]💡 Suggestion:[/bold green]")
                        
                        context = self._build_context_for_page(content_to_analyze)
                        prompt = PromptTemplates.get_taxact_assistant_prompt(content_to_analyze, context)
                        
                        full_response = ""
                        for chunk in self.llm.stream_chat([
                            {"role": "system", "content": PromptTemplates.get_assistant_system_prompt()},
                            {"role": "user", "content": prompt},
                        ]):
                            full_response += chunk
                            print(chunk, end="", flush=True)
                        print()
                        
                        content_to_analyze = None
                
                if not watching:
                    self.console.print("\n[yellow]Watch mode stopped.[/yellow]")
        
        except Exception as e:
            self.console.print(f"[red]Error in watch mode: {e}[/red]")
            logger.error(f"Watch mode error: {e}")
    
    def _show_summary(self) -> None:
        """Show tax data summary."""
        tax_year = self.db.get_tax_year(self.tax_year)
        
        if not tax_year:
            self.console.print(f"[yellow]No data found for year {self.tax_year}[/yellow]")
            return
        
        summary = self.db.get_tax_summary(tax_year.id)
        
        # Create summary table
        table = Table(title=f"Tax Summary for {self.tax_year}")
        table.add_column("Category", style="cyan")
        table.add_column("Count", justify="right")
        table.add_column("Amount", justify="right", style="green")
        
        table.add_row("W-2 Wages", str(summary["w2_count"]), f"${summary['total_wages']:,.2f}")
        table.add_row("1099-INT Interest", str(summary["form_1099_int_count"]), f"${summary['total_interest']:,.2f}")
        table.add_row("1099-DIV Dividends", str(summary["form_1099_div_count"]), f"${summary['total_dividends']:,.2f}")
        table.add_row("Qualified Dividends", "-", f"${summary['total_qualified_dividends']:,.2f}")
        
        self.console.print(table)
        
        # Tax withheld table
        table2 = Table(title="Tax Withheld")
        table2.add_column("Type", style="cyan")
        table2.add_column("Amount", justify="right", style="yellow")
        
        table2.add_row("Federal Tax Withheld", f"${summary['total_federal_withheld']:,.2f}")
        table2.add_row("State Tax Withheld", f"${summary['total_state_withheld']:,.2f}")
        
        self.console.print(table2)
    
    def _show_forms(self) -> None:
        """Show list of available tax forms."""
        tax_year = self.db.get_tax_year(self.tax_year)
        
        if not tax_year:
            self.console.print(f"[yellow]No data found for year {self.tax_year}[/yellow]")
            return
        
        documents = self.db.list_documents(tax_year_id=tax_year.id)
        
        if not documents:
            self.console.print("[yellow]No documents found.[/yellow]")
            return
        
        table = Table(title="Tax Documents")
        table.add_column("Type", style="cyan")
        table.add_column("File Name", style="blue")
        table.add_column("Status", style="yellow")
        
        for doc in documents:
            table.add_row(
                doc.document_type.value,
                doc.file_name,
                doc.processing_status.value,
            )
        
        self.console.print(table)
    
    def _show_document_details(self) -> None:
        """Show extracted details from all documents."""
        from rich.table import Table
        from rich.panel import Panel
        from rich.text import Text
        from src.storage.models import DocumentType
        
        tax_year = self.db.get_tax_year(self.tax_year)
        
        if not tax_year:
            self.console.print(f"[yellow]No data found for year {self.tax_year}[/yellow]")
            return
        
        documents = self.db.list_documents(tax_year_id=tax_year.id)
        
        if not documents:
            self.console.print("[yellow]No documents found.[/yellow]")
            return
        
        for doc in documents:
            if doc.processing_status.value != "validated":
                continue
            
            self.console.print(Panel(f"[bold cyan]{doc.document_type.value}: {doc.file_name}[/bold cyan]"))
            
            if doc.document_type == DocumentType.W2:
                w2_data = self.db.get_w2_data(doc.id)
                if w2_data:
                    self.console.print(f"  [cyan]Employer:[/cyan] {w2_data.employer_name}")
                    self.console.print(f"  [cyan]Employer EIN:[/cyan] {w2_data.employer_ein}")
                    self.console.print(f"  [cyan]Employee:[/cyan] {w2_data.employee_name}")
                    self.console.print(f"  [cyan]Employee SSN:[/cyan] {w2_data.employee_ssn}")
                    self.console.print(f"  [cyan]Wages (Box 1):[/cyan] ${w2_data.wages_tips_compensation:,.2f}")
                    self.console.print(f"  [cyan]Federal Tax (Box 2):[/cyan] ${w2_data.federal_income_tax_withheld:,.2f}")
                    self.console.print(f"  [cyan]Social Security Wages (Box 3):[/cyan] ${w2_data.social_security_wages:,.2f}")
                    self.console.print(f"  [cyan]Social Security Tax (Box 4):[/cyan] ${w2_data.social_security_tax_withheld:,.2f}")
                    self.console.print(f"  [cyan]Medicare Wages (Box 5):[/cyan] ${w2_data.medicare_wages:,.2f}")
                    self.console.print(f"  [cyan]Medicare Tax (Box 6):[/cyan] ${w2_data.medicare_tax_withheld:,.2f}")
                    if w2_data.state_wages_tips:
                        self.console.print(f"  [cyan]State Wages (Box 16):[/cyan] ${w2_data.state_wages_tips:,.2f}")
                    if w2_data.state_income_tax:
                        self.console.print(f"  [cyan]State Tax (Box 17):[/cyan] ${w2_data.state_income_tax:,.2f}")
            
            elif doc.document_type == DocumentType.FORM_1099_INT:
                int_data = self.db.get_1099_int_data(doc.id)
                if int_data:
                    self.console.print(f"  [cyan]Payer:[/cyan] {int_data.payer_name}")
                    self.console.print(f"  [cyan]Payer TIN:[/cyan] {int_data.payer_tin}")
                    self.console.print(f"  [cyan]Recipient:[/cyan] {int_data.recipient_name}")
                    self.console.print(f"  [cyan]Recipient TIN:[/cyan] {int_data.recipient_tin}")
                    self.console.print(f"  [cyan]Interest Income (Box 1):[/cyan] ${int_data.interest_income:,.2f}")
                    if int_data.tax_exempt_interest:
                        self.console.print(f"  [cyan]Tax-Exempt Interest (Box 8):[/cyan] ${int_data.tax_exempt_interest:,.2f}")
                    if int_data.federal_income_tax_withheld:
                        self.console.print(f"  [cyan]Federal Tax Withheld (Box 4):[/cyan] ${int_data.federal_income_tax_withheld:,.2f}")
                    if int_data.foreign_tax_paid:
                        self.console.print(f"  [cyan]Foreign Tax Paid (Box 6):[/cyan] ${int_data.foreign_tax_paid:,.2f}")
            
            elif doc.document_type == DocumentType.FORM_1099_DIV:
                div_data = self.db.get_1099_div_data(doc.id)
                if div_data:
                    self.console.print(f"  [cyan]Payer:[/cyan] {div_data.payer_name}")
                    self.console.print(f"  [cyan]Payer TIN:[/cyan] {div_data.payer_tin}")
                    self.console.print(f"  [cyan]Recipient:[/cyan] {div_data.recipient_name}")
                    self.console.print(f"  [cyan]Recipient TIN:[/cyan] {div_data.recipient_tin}")
                    self.console.print(f"  [cyan]Total Ordinary Dividends (Box 1a):[/cyan] ${div_data.total_ordinary_dividends:,.2f}")
                    if div_data.qualified_dividends:
                        self.console.print(f"  [cyan]Qualified Dividends (Box 1b):[/cyan] ${div_data.qualified_dividends:,.2f}")
                    if div_data.section_199a_dividends:
                        self.console.print(f"  [cyan]Section 199A Dividends (Box 5):[/cyan] ${div_data.section_199a_dividends:,.2f}")
                    if div_data.federal_income_tax_withheld:
                        self.console.print(f"  [cyan]Federal Tax Withheld (Box 4):[/cyan] ${div_data.federal_income_tax_withheld:,.2f}")
                    if div_data.foreign_tax_paid:
                        self.console.print(f"  [cyan]Foreign Tax Paid (Box 7):[/cyan] ${div_data.foreign_tax_paid:,.2f}")
            
            self.console.print()
    
    def _handle_process_file(self, file_path: str) -> None:
        """Handle document file processing command."""
        from pathlib import Path
        from src.ocr import PDFProcessor, DocumentClassifier
        
        path = Path(file_path)
        
        if not path.exists():
            self.console.print(f"[red]File not found: {file_path}[/red]")
            return
        
        self.console.print(f"[blue]Processing {path.name}...[/blue]")
        
        try:
            tax_year = self.db.get_or_create_tax_year(self.tax_year)
            
            file_hash = get_file_hash(path)
            if self.db.document_exists_by_hash(tax_year.id, file_hash):
                self.console.print(f"[yellow]File already processed: {path.name}[/yellow]")
                return
            
            pdf_processor = PDFProcessor()
            classifier = DocumentClassifier()
            validator = DataValidator(self.tax_year)
            
            doc = self.db.create_document(
                tax_year_id=tax_year.id,
                document_type=DocumentType.UNKNOWN,
                file_name=path.name,
                file_path=str(path),
                file_hash=file_hash,
            )
            
            self.db.update_document_status(doc.id, ProcessingStatus.PROCESSING)
            
            if path.suffix.lower() == ".pdf":
                text = pdf_processor.extract_text(path)
            else:
                text = ""
            
            self.db.update_document_ocr_text(doc.id, text)
            
            doc_type, confidence = classifier.classify(text)
            self.db.update_document_type(doc.id, doc_type)
            
            # Extract data
            extraction_success = False
            if doc_type == DocumentType.W2:
                data = self._extract_w2_via_pdfplumber_tax(path, doc.id)
                if data:
                    is_valid, errors = validator.validate_w2(data)
                    if is_valid:
                        self.db.save_w2_data(data)
                        self.console.print(f"[green][OK] Extracted W-2 data from {path.name}[/green]")
                        extraction_success = True
                    else:
                        self.console.print(f"[red]W-2 validation failed: {errors}[/red]")
                else:
                    self.console.print(f"[red]W-2 extraction failed - no data returned[/red]")
            
            elif doc_type == DocumentType.FORM_1099_INT:
                data = self._extract_1099_int_via_pdfplumber_tax(path, doc.id)
                if data:
                    self.db.save_1099_int_data(data)
                    self.console.print(f"[green][OK] Extracted 1099-INT data from {path.name}[/green]")
                    extraction_success = True
                else:
                    self.console.print(f"[red]1099-INT extraction failed - no data returned[/red]")
            
            elif doc_type == DocumentType.FORM_1099_DIV:
                data = self._extract_1099_div_via_pdfplumber_tax(path, doc.id)
                if data:
                    self.db.save_1099_div_data(data)
                    self.console.print(f"[green][OK] Extracted 1099-DIV data from {path.name}[/green]")
                    extraction_success = True
                else:
                    self.console.print(f"[red]1099-DIV extraction failed - no data returned[/red]")
            
            else:
                self.console.print(f"[yellow]Document type {doc_type.value} for {path.name} - stored for reference[/yellow]")
                extraction_success = True
            
            # Update status based on extraction result
            if extraction_success:
                self.db.update_document_status(doc.id, ProcessingStatus.VALIDATED)
            else:
                self.db.update_document_status(doc.id, ProcessingStatus.ERROR)
            
        except Exception as e:
            logger.error(f"Failed to process {path.name}: {e}")
            self.console.print(f"[red]Error processing file: {e}[/red]")
            if doc:
                self.db.update_document_status(doc.id, ProcessingStatus.ERROR)
    
    def _show_help(self) -> None:
        """Show help information."""
        self.console.print(Panel(
            "[bold]Available Commands:[/bold]\n\n"
            "[cyan]watch[/cyan] - Monitor tax software and get suggestions\n"
            "[cyan]analyze[/cyan] - Analyze current Chrome page now\n"
            "[cyan]summary[/cyan] - Show your tax data summary\n"
            "[cyan]forms[/cyan] - List your tax documents\n"
            "[cyan]details[/cyan] - Show extracted document fields\n"
            "[cyan]clear[/cyan] - Clear conversation history\n"
            "[cyan]help[/cyan] - Show this help message\n"
            "[cyan]quit[/cyan] - Exit the assistant\n\n"
            "[bold]Tips:[/bold]\n"
            "• Ask questions like 'Where do I enter my W-2 wages?'\n"
            "• Ask about specific forms: 'What is Box 12 code D on W-2?'\n"
            "• Get help with TaxAct: 'I'm on the income section, what do I do?'\n"
            "• Use 'watch' to monitor tax software and get contextual suggestions\n"
            "• File watcher monitors data/ - new documents are auto-processed",
            title="Help",
        ))
    
    def get_value_for_field(self, field_name: str) -> Optional[str]:
        """
        Get the value for a specific tax field.
        
        Args:
            field_name: Name of the tax field
        
        Returns:
            Value as string or None
        """
        tax_year = self.db.get_tax_year(self.tax_year)
        
        if not tax_year:
            return None
        
        field_lower = field_name.lower()
        
        # Check W-2 fields
        w2_list = self.db.list_w2_data(tax_year.id)
        for w2 in w2_list:
            if "wage" in field_lower and "social" not in field_lower:
                return f"${w2.wages_tips_compensation:,.2f}"
            elif "federal" in field_lower and "withheld" in field_lower:
                return f"${w2.federal_income_tax_withheld:,.2f}"
            elif "social security" in field_lower and "wage" in field_lower:
                return f"${w2.social_security_wages:,.2f}"
            elif "medicare" in field_lower and "wage" in field_lower:
                return f"${w2.medicare_wages:,.2f}"
            elif "employer" in field_lower:
                return w2.employer_name
        
        # Check 1099-INT fields
        int_list = self.db.list_1099_int_data(tax_year.id)
        total_interest = sum(f.interest_income for f in int_list)
        if "interest" in field_lower:
            return f"${total_interest:,.2f}"
        
        # Check 1099-DIV fields
        div_list = self.db.list_1099_div_data(tax_year.id)
        total_div = sum(f.total_ordinary_dividends for f in div_list)
        if "dividend" in field_lower:
            return f"${total_div:,.2f}"
        
        return None
    
    def search_documents(self, query: str) -> list[dict]:
        """
        Search for relevant documents using semantic search.
        
        Args:
            query: Search query
        
        Returns:
            List of matching documents
        """
        if self.qdrant is None:
            try:
                self.qdrant = QdrantHandler()
            except Exception:
                return []
        
        return self.qdrant.search(query, tax_year=self.tax_year)