"""
Tax filing assistant module.
Provides interactive assistance for tax filing using LLM and extracted data.
"""

from decimal import Decimal
from typing import Optional

from rich.console import Console
from rich.panel import Panel
from rich.prompt import Prompt
from rich.table import Table
from rich import print as rprint

from src.storage import SQLiteHandler, QdrantHandler
from src.extraction import LLMExtractor
from src.extraction.prompts import PromptTemplates
from src.utils import get_logger

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


class TaxAssistant:
    """
    Interactive tax filing assistant.
    Helps users fill out tax forms using extracted data and LLM guidance.
    """
    
    def __init__(self, tax_year: int, auto_load_guidance: bool = True):
        """
        Initialize the tax assistant.
        
        Args:
            tax_year: Tax year to assist with
            auto_load_guidance: Automatically load tax guidance if directories exist
        """
        self.tax_year = tax_year
        self.db = SQLiteHandler()
        self.llm = LLMExtractor(temperature=0.3)
        self.qdrant: Optional[QdrantHandler] = None
        self.screen_reader: Optional[ScreenReader] = None
        self.console = Console()
        
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
                        logger.info(f"Auto-loaded tax guidance: {results}")
            except Exception as e:
                logger.debug(f"Auto-load guidance failed: {e}")
        
        # Initialize system prompt
        self._init_conversation()
    
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
    
    def chat(self, message: str) -> str:
        """
        Send a message to the assistant and get a response.
        
        Args:
            message: User message
        
        Returns:
            Assistant response
        """
        # Retrieve relevant tax guidance for this query
        guidance_context = self._retrieve_tax_guidance(message)
        
        # Build message with guidance context if available
        if guidance_context:
            enhanced_message = f"{message}\n\n{guidance_context}"
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
        """Retrieve relevant tax guidance for a query."""
        if not TAX_GUIDANCE_AVAILABLE:
            return ""
        
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
            
            return guidance
        except Exception as e:
            logger.debug(f"Could not retrieve tax guidance: {e}")
            return ""
    
    def run_interactive(self) -> None:
        """Run the interactive assistant session."""
        # Build status message
        status_parts = [f"Tax Year: {self.tax_year}"]
        if self._guidance_loaded:
            status_parts.append("[green]✓ Tax guidance loaded[/green]")
        
        self.console.print(Panel(
            f"[bold blue]Tax Filing Assistant[/bold blue]\n"
            + "\n".join(status_parts) + "\n\n"
            "Commands:\n"
            "  [cyan]capture[/cyan] - Capture screen and get help\n"
            "  [cyan]summary[/cyan] - Show tax data summary\n"
            "  [cyan]forms[/cyan] - List available forms\n"
            "  [cyan]help[/cyan] - Show available commands\n"
            "  [cyan]quit[/cyan] - Exit the assistant",
            title="Welcome",
        ))
        
        while True:
            try:
                user_input = Prompt.ask("\n[bold green]You[/bold green]").strip()
                
                if not user_input:
                    continue
                
                # Handle commands
                if user_input.lower() in ["quit", "exit", "q"]:
                    self.console.print("[yellow]Goodbye![/yellow]")
                    break
                
                elif user_input.lower() == "capture":
                    self._handle_capture()
                    continue
                
                elif user_input.lower() == "summary":
                    self._show_summary()
                    continue
                
                elif user_input.lower() == "forms":
                    self._show_forms()
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
                self.console.print("\n[yellow]Goodbye![/yellow]")
                break
            
            except Exception as e:
                self.console.print(f"[red]Error: {e}[/red]")
                logger.error(f"Error in interactive session: {e}")
    
    def _handle_capture(self) -> None:
        """Handle screen capture command."""
        if not SCREEN_READER_AVAILABLE:
            self.console.print("[red]Screen reader not available. Install mss and pytesseract.[/red]")
            return
        
        try:
            if self.screen_reader is None:
                self.screen_reader = ScreenReader()
            
            self.console.print("[blue]Capturing screen...[/blue]")
            
            # Capture and OCR
            image, text = self.screen_reader.capture_and_ocr()
            
            if not text:
                self.console.print("[yellow]No text detected on screen.[/yellow]")
                return
            
            # Get assistance from LLM
            context = self._build_user_context()
            prompt = PromptTemplates.get_taxact_assistant_prompt(text, context)
            
            with self.console.status("[bold blue]Analyzing screen...[/bold blue]"):
                response = self.llm.chat([
                    {"role": "system", "content": PromptTemplates.get_assistant_system_prompt()},
                    {"role": "user", "content": prompt},
                ])
            
            self.console.print(f"\n[bold blue]Screen Analysis:[/bold blue]\n{response}")
        
        except Exception as e:
            self.console.print(f"[red]Error capturing screen: {e}[/red]")
            logger.error(f"Screen capture error: {e}")
    
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
    
    def _show_help(self) -> None:
        """Show help information."""
        self.console.print(Panel(
            "[bold]Available Commands:[/bold]\n\n"
            "[cyan]capture[/cyan] - Capture your screen and get assistance\n"
            "[cyan]summary[/cyan] - Show your tax data summary\n"
            "[cyan]forms[/cyan] - List your tax documents\n"
            "[cyan]clear[/cyan] - Clear conversation history\n"
            "[cyan]help[/cyan] - Show this help message\n"
            "[cyan]quit[/cyan] - Exit the assistant\n\n"
            "[bold]Tips:[/bold]\n"
            "• Ask questions like 'Where do I enter my W-2 wages?'\n"
            "• Ask about specific forms: 'What is Box 12 code D on W-2?'\n"
            "• Get help with TaxAct: 'I'm on the income section, what do I do?'\n"
            "• Use 'capture' when you need help with a specific screen",
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