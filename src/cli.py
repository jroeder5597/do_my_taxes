"""
Command-line interface for the tax document processor.
"""

import json
from pathlib import Path
from typing import Optional

import click
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.progress import Progress, SpinnerColumn, TextColumn

from src.utils import setup_logger, get_logger, ensure_dir, get_file_hash, list_documents
from src.utils.config import get_settings
from src.storage import SQLiteHandler, QdrantHandler, DocumentType, ProcessingStatus
from src.ocr import PDFProcessor, DocumentClassifier, FlyfieldExtractor
from src.extraction import DataValidator

console = Console()
logger = get_logger()


@click.group()
@click.option("--debug", is_flag=True, help="Enable debug logging")
@click.pass_context
def cli(ctx: click.Context, debug: bool) -> None:
    """Tax Document Processor - OCR and LLM-based tax document processing."""
    # Setup logging
    log_level = "DEBUG" if debug else "INFO"
    setup_logger(level=log_level, log_file="logs/tax_processor.log")
    
    # Store context
    ctx.ensure_object(dict)
    ctx.obj["debug"] = debug


@cli.command()
@click.option("--year", type=int, required=True, help="Tax year")
@click.option("--input", "-i", "input_path", type=click.Path(exists=True), required=True,
              help="Input file or directory")
@click.option("--recursive", "-r", is_flag=True, default=True, help="Process directory recursively")
@click.pass_context
def process(ctx: click.Context, year: int, input_path: str, recursive: bool) -> None:
    """Process tax documents from a file or directory."""
    input_dir = Path(input_path)
    
    # Initialize handlers
    db = SQLiteHandler()
    
    # Get or create tax year
    tax_year = db.get_or_create_tax_year(year)
    console.print(f"[green]Tax year: {year}[/green]")
    
    # Get list of documents to process
    if input_dir.is_file():
        files = [input_dir]
    else:
        files = list(list_documents(input_dir, recursive=recursive))
    
    if not files:
        console.print("[yellow]No documents found to process.[/yellow]")
        return
    
    console.print(f"[blue]Found {len(files)} document(s) to process[/blue]")
    
    # Initialize processors
    settings = get_settings()
    pdf_processor = PDFProcessor()
    classifier = DocumentClassifier()
    flyfield = FlyfieldExtractor()
    validator = DataValidator(year)
    qdrant = None  # Lazy load
    
    # Auto-start all services
    try:
        from src.utils.service_manager import ensure_services
        services = ensure_services(console)
    except Exception as e:
        console.print(f"[yellow]Could not start all services: {e}[/yellow]")
    
    # Try to start Qdrant service for semantic search
    try:
        from src.storage.qdrant_manager import QdrantManager
        qdrant_manager = QdrantManager()
        if qdrant_manager.is_container_running():
            qdrant = QdrantHandler()
    except Exception:
        pass
    
    # Process each document
    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        console=console,
    ) as progress:
        for file_path in files:
            task = progress.add_task(f"Processing {file_path.name}...", total=None)
            
            try:
                # Check if already processed
                file_hash = get_file_hash(file_path)
                if db.document_exists_by_hash(tax_year.id, file_hash):
                    console.print(f"[yellow]Skipping {file_path.name} (already processed)[/yellow]")
                    continue
                
                # Create document record
                doc = db.create_document(
                    tax_year_id=tax_year.id,
                    document_type=DocumentType.UNKNOWN,
                    file_name=file_path.name,
                    file_path=str(file_path),
                    file_hash=file_hash,
                )
                
                # Extract text
                db.update_document_status(doc.id, ProcessingStatus.PROCESSING)
                
                if file_path.suffix.lower() == ".pdf":
                    text = pdf_processor.extract_text(file_path)
                else:
                    text = ""
                
                # Update OCR text
                db.update_document_ocr_text(doc.id, text)
                
                # Classify document
                doc_type, confidence = classifier.classify(text)
                
                # Extract data using flyfield
                data = None
                if doc_type == DocumentType.W2:
                    from decimal import Decimal
                    from src.storage.models import W2Data
                    
                    extracted = flyfield.extract_w2_from_file(str(file_path))
                    if extracted and extracted.get('wages_tips_compensation'):
                        def to_decimal(val, default='0'):
                            if val is None:
                                return Decimal(default)
                            return Decimal(str(val).replace(',', ''))
                        
                        data = W2Data(
                            document_id=doc.id,
                            employer_ein=extracted.get('employer_ein'),
                            employer_name=extracted.get('employer_name', ''),
                            employer_address=extracted.get('employer_address'),
                            employer_state=extracted.get('employer_state'),
                            employee_name=extracted.get('employee_name', ''),
                            employee_ssn=extracted.get('employee_ssn'),
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
                        
                        is_valid, errors = validator.validate_w2(data)
                        if not is_valid:
                            console.print(f"[red]W-2 validation failed: {errors}[/red]")
                        else:
                            db.save_w2_data(data)
                            console.print(f"[green]Extracted W-2 data from {file_path.name}[/green]")
                            if qdrant:
                                try:
                                    extracted_fields = {
                                        "employer_name": data.employer_name,
                                        "wages": float(data.wages_tips_compensation) if data.wages_tips_compensation else 0,
                                        "federal_tax_withheld": float(data.federal_income_tax_withheld) if data.federal_income_tax_withheld else 0,
                                    }
                                    qdrant.store_document(
                                        document_id=doc.id,
                                        ocr_text=text,
                                        document_type=doc_type,
                                        tax_year=year,
                                        file_name=file_path.name,
                                        extracted_fields=extracted_fields,
                                    )
                                except Exception as e:
                                    logger.warning(f"Failed to store document in Qdrant: {e}")
                
                else:
                    console.print(f"[yellow]Document type {doc_type.value} for {file_path.name} - stored for reference[/yellow]")
                
                db.update_document_status(doc.id, ProcessingStatus.VALIDATED)
                
            except Exception as e:
                console.print(f"[red]Error processing {file_path.name}: {e}[/red]")
                logger.error(f"Error processing {file_path.name}: {e}")
                if 'doc' in locals():
                    db.update_document_status(doc.id, ProcessingStatus.ERROR, str(e))
            
            progress.remove_task(task)
    
    console.print("[green]Processing complete![/green]")


@cli.command("list")
@click.option("--year", type=int, help="Filter by tax year")
@click.option("--type", "doc_type", type=click.Choice(["W2", "1099_INT", "1099_DIV", "ALL"]),
              default="ALL", help="Filter by document type")
@click.pass_context
def list_docs(ctx: click.Context, year: Optional[int], doc_type: str) -> None:
    """List processed documents."""
    db = SQLiteHandler()
    
    # Get tax years
    if year:
        tax_year = db.get_tax_year(year)
        if not tax_year:
            console.print(f"[yellow]No data found for year {year}[/yellow]")
            return
        tax_years = [tax_year]
    else:
        tax_years = db.list_tax_years()
    
    if not tax_years:
        console.print("[yellow]No tax years found. Process some documents first.[/yellow]")
        return
    
    for tax_year in tax_years:
        console.print(f"\n[bold blue]Tax Year: {tax_year.year}[/bold blue]")
        
        # Get documents
        documents = db.list_documents(tax_year_id=tax_year.id)
        
        if not documents:
            console.print("[yellow]No documents found.[/yellow]")
            continue
        
        # Create table
        table = Table(title=f"Documents for {tax_year.year}")
        table.add_column("ID", style="cyan")
        table.add_column("Type", style="green")
        table.add_column("File Name", style="blue")
        table.add_column("Status", style="yellow")
        
        for doc in documents:
            if doc_type != "ALL" and doc.document_type.value != doc_type:
                continue
            table.add_row(
                str(doc.id),
                doc.document_type.value,
                doc.file_name,
                doc.processing_status.value,
            )
        
        console.print(table)


@cli.command()
@click.option("--year", type=int, required=True, help="Tax year")
@click.pass_context
def summary(ctx: click.Context, year: int) -> None:
    """Show tax summary for a year."""
    db = SQLiteHandler()
    
    tax_year = db.get_tax_year(year)
    if not tax_year:
        console.print(f"[yellow]No data found for year {year}[/yellow]")
        return
    
    summary_data = db.get_tax_summary(tax_year.id)
    
    # Create summary panel
    console.print(Panel(f"[bold blue]Tax Summary for {year}[/bold blue]", expand=False))
    
    # Income table
    table = Table(title="Income Summary")
    table.add_column("Source", style="cyan")
    table.add_column("Count", justify="right")
    table.add_column("Amount", justify="right", style="green")
    
    table.add_row(
        "W-2 Wages",
        str(summary_data["w2_count"]),
        f"${summary_data['total_wages']:,.2f}",
    )
    table.add_row(
        "1099-INT Interest",
        str(summary_data["form_1099_int_count"]),
        f"${summary_data['total_interest']:,.2f}",
    )
    table.add_row(
        "1099-DIV Dividends",
        str(summary_data["form_1099_div_count"]),
        f"${summary_data['total_dividends']:,.2f}",
    )
    
    console.print(table)
    
    # Tax withheld table
    table2 = Table(title="Tax Withheld")
    table2.add_column("Type", style="cyan")
    table2.add_column("Amount", justify="right", style="yellow")
    
    table2.add_row("Federal Tax Withheld", f"${summary_data['total_federal_withheld']:,.2f}")
    table2.add_row("State Tax Withheld", f"${summary_data['total_state_withheld']:,.2f}")
    
    console.print(table2)


@cli.command()
@click.option("--year", type=int, required=True, help="Tax year")
@click.option("--query", "-q", required=True, help="Search query")
@click.option("--limit", "-l", default=5, help="Maximum results")
@click.pass_context
def query(ctx: click.Context, year: int, query: str, limit: int) -> None:
    """Search documents using semantic search."""
    try:
        qdrant = QdrantHandler()
    except Exception as e:
        console.print(f"[red]Vector search not available: {e}[/red]")
        return
    
    results = qdrant.search(query, limit=limit, tax_year=year)
    
    if not results:
        console.print("[yellow]No results found.[/yellow]")
        return
    
    console.print(f"[bold blue]Search Results for: {query}[/bold blue]\n")
    
    for i, result in enumerate(results, 1):
        console.print(Panel(
            f"[bold]{result['document_type']}[/bold] - {result['file_name']}\n"
            f"Score: {result['score']:.3f}\n\n"
            f"{result['ocr_text'][:300]}...",
            title=f"Result {i}",
        ))


@cli.command()
@click.option("--year", type=int, required=True, help="Tax year")
@click.option("--format", "-f", type=click.Choice(["json", "csv"]), default="json",
              help="Export format")
@click.option("--output", "-o", type=click.Path(), default="data/exports",
              help="Output directory")
@click.pass_context
def export(ctx: click.Context, year: int, format: str, output: str) -> None:
    """Export tax data to file."""
    db = SQLiteHandler()
    
    tax_year = db.get_tax_year(year)
    if not tax_year:
        console.print(f"[yellow]No data found for year {year}[/yellow]")
        return
    
    # Ensure output directory exists
    output_dir = ensure_dir(output)
    
    # Collect all data
    export_data = {
        "tax_year": year,
        "w2_forms": [],
        "form_1099_int": [],
        "form_1099_div": [],
    }
    
    # Get W-2 data
    for w2 in db.list_w2_data(tax_year.id):
        export_data["w2_forms"].append(w2.model_dump())
    
    # Get 1099-INT data
    for form in db.list_1099_int_data(tax_year.id):
        export_data["form_1099_int"].append(form.model_dump())
    
    # Get 1099-DIV data
    for form in db.list_1099_div_data(tax_year.id):
        export_data["form_1099_div"].append(form.model_dump())
    
    # Export
    if format == "json":
        output_file = output_dir / f"tax_data_{year}.json"
        with open(output_file, "w") as f:
            json.dump(export_data, f, indent=2, default=str)
        console.print(f"[green]Exported to {output_file}[/green]")
    
    elif format == "csv":
        import csv
        
        # Export W-2 data
        if export_data["w2_forms"]:
            w2_file = output_dir / f"w2_data_{year}.csv"
            with open(w2_file, "w", newline="") as f:
                writer = csv.DictWriter(f, fieldnames=export_data["w2_forms"][0].keys())
                writer.writeheader()
                writer.writerows(export_data["w2_forms"])
            console.print(f"[green]Exported W-2 data to {w2_file}[/green]")
        
        # Export 1099-INT data
        if export_data["form_1099_int"]:
            int_file = output_dir / f"1099_int_data_{year}.csv"
            with open(int_file, "w", newline="") as f:
                writer = csv.DictWriter(f, fieldnames=export_data["form_1099_int"][0].keys())
                writer.writeheader()
                writer.writerows(export_data["form_1099_int"])
            console.print(f"[green]Exported 1099-INT data to {int_file}[/green]")
        
        # Export 1099-DIV data
        if export_data["form_1099_div"]:
            div_file = output_dir / f"1099_div_data_{year}.csv"
            with open(div_file, "w", newline="") as f:
                writer = csv.DictWriter(f, fieldnames=export_data["form_1099_div"][0].keys())
                writer.writeheader()
                writer.writerows(export_data["form_1099_div"])
            console.print(f"[green]Exported 1099-DIV data to {div_file}[/green]")


@cli.command()
@click.pass_context
def check_llm(ctx: click.Context) -> None:
    """Check LLM (Ollama) connection and model availability."""
    console.print("[blue]Checking Ollama connection...[/blue]")
    
    try:
        from src.extraction import LLMExtractor
        settings = get_settings()
        extractor = LLMExtractor(
            model=settings.llm.ollama.model,
            base_url=settings.llm.ollama.base_url,
        )
        
        if extractor.check_connection():
            console.print("[green]Ollama is running and accessible[/green]")
            
            response = extractor.chat([
                {"role": "user", "content": "Say 'hello' in one word."}
            ])
            console.print(f"[green]Model responded: {response[:50]}...[/green]")
        else:
            console.print("[red]Cannot connect to Ollama[/red]")
            console.print("[yellow]Make sure Ollama is running: ollama serve[/yellow]")
    
    except Exception as e:
        console.print(f"[red]Error: {e}[/red]")


@cli.command()
@click.option("--port", type=int, default=5001, help="Port for Flyfield service")
@click.pass_context
def start_flyfield(ctx: click.Context, port: int) -> None:
    """Start the Flyfield PDF extraction container service."""
    console.print("[blue]Starting Flyfield service...[/blue]")
    
    try:
        from src.ocr.flyfield_manager import FlyfieldPodmanManager
        
        manager = FlyfieldPodmanManager(port=port)
        
        if not manager.is_podman_available():
            console.print("[red]Podman is not available[/red]")
            console.print("[yellow]Install Podman to use containerized PDF extraction.[/yellow]")
            return
        
        if not manager.is_image_built():
            console.print("[blue]Building Flyfield image (this may take a few minutes)...[/blue]")
            if not manager.build_image():
                console.print("[red]Failed to build Flyfield image[/red]")
                return
            console.print("[green]Flyfield image built successfully[/green]")
        
        service_url = manager.ensure_service_running(auto_build=False)
        if service_url:
            console.print(f"[green]Flyfield service started at {service_url}[/green]")
        else:
            console.print("[red]Failed to start Flyfield service[/red]")
    
    except ImportError as e:
        console.print(f"[red]Flyfield manager not available: {e}[/red]")
    except Exception as e:
        console.print(f"[red]Error starting Flyfield service: {e}[/red]")


@cli.command()
@click.pass_context
def stop_flyfield(ctx: click.Context) -> None:
    """Stop the Flyfield container service."""
    console.print("[blue]Stopping Flyfield service...[/blue]")
    
    try:
        from src.ocr.flyfield_manager import FlyfieldPodmanManager
        
        manager = FlyfieldPodmanManager()
        
        if manager.stop_container():
            console.print("[green]Flyfield service stopped[/green]")
        else:
            console.print("[yellow]Flyfield service was not running[/yellow]")
    
    except ImportError as e:
        console.print(f"[red]Flyfield manager not available: {e}[/red]")
    except Exception as e:
        console.print(f"[red]Error stopping Flyfield service: {e}[/red]")


@cli.command()
@click.pass_context
def build_flyfield(ctx: click.Context) -> None:
    """Build the Flyfield Podman image."""
    console.print("[blue]Building Flyfield Podman image...[/blue]")
    
    try:
        from src.ocr.flyfield_manager import FlyfieldPodmanManager
        
        manager = FlyfieldPodmanManager()
        
        if not manager.is_podman_available():
            console.print("[red]Podman is not available[/red]")
            return
        
        if manager.build_image():
            console.print("[green]Flyfield image built successfully[/green]")
        else:
            console.print("[red]Failed to build Flyfield image[/red]")
    
    except ImportError as e:
        console.print(f"[red]Flyfield manager not available: {e}[/red]")
    except Exception as e:
        console.print(f"[red]Error building Flyfield image: {e}[/red]")


@cli.command()
@click.pass_context
def check_flyfield(ctx: click.Context) -> None:
    """Check Flyfield service status."""
    console.print("[blue]Checking Flyfield service status...[/blue]")
    
    try:
        from src.ocr.flyfield_manager import get_flyfield_status
        
        status = get_flyfield_status()
        
        table = Table(title="Flyfield Service Status")
        table.add_column("Component", style="cyan")
        table.add_column("Status", style="green")
        
        table.add_row("Podman Available", "Yes" if status["podman_available"] else "No")
        table.add_row("Image Built", "Yes" if status["image_built"] else "No")
        table.add_row("Container Running", "Yes" if status["container_running"] else "No")
        table.add_row("Service Healthy", "Yes" if status["service_healthy"] else "No")
        table.add_row("Service URL", status["service_url"] or "N/A")
        
        console.print(table)
        
        if not status["podman_available"]:
            console.print("[yellow]Podman is not available.[/yellow]")
        elif not status["image_built"]:
            console.print("[yellow]Flyfield image not built. Run: python -m src.cli build-flyfield[/yellow]")
        elif not status["container_running"]:
            console.print("[yellow]Flyfield container not running. Run: python -m src.cli start-flyfield[/yellow]")
        elif not status["service_healthy"]:
            console.print("[yellow]Flyfield service is not healthy. Check container logs.[/yellow]")
        else:
            console.print("[green]Flyfield service is running and healthy![/green]")
    
    except ImportError as e:
        console.print(f"[red]Flyfield manager not available: {e}[/red]")
    except Exception as e:
        console.print(f"[red]Error checking Flyfield status: {e}[/red]")


@cli.command()
@click.pass_context
def check_qdrant(ctx: click.Context) -> None:
    """Check Qdrant connection."""
    console.print("[blue]Checking Qdrant connection...[/blue]")
    
    try:
        qdrant = QdrantHandler()
        
        if qdrant.check_connection():
            console.print("[green]✓ Qdrant is running and accessible[/green]")
            
            info = qdrant.get_collection_info()
            console.print(f"[blue]Collection: {info.get('name', 'N/A')}[/blue]")
            console.print(f"[blue]Points: {info.get('points_count', 0)}[/blue]")
        else:
            console.print("[red]✗ Cannot connect to Qdrant[/red]")
            console.print("[yellow]Start Qdrant with: python -m src.cli start-qdrant[/yellow]")
    
    except Exception as e:
        console.print(f"[red]✗ Error: {e}[/red]")


@cli.command()
@click.pass_context
def start_qdrant(ctx: click.Context) -> None:
    """Start the Qdrant container service."""
    console.print("[blue]Starting Qdrant service...[/blue]")
    
    try:
        from src.storage.qdrant_manager import QdrantManager
        
        manager = QdrantManager()
        
        if not manager.is_podman_available():
            console.print("[red]Podman is not available[/red]")
            console.print("[yellow]Install Podman: https://podman.io/getting-started/installation[/yellow]")
            return
        
        # Pull image if not present
        if not manager.is_image_available():
            console.print("[blue]Pulling Qdrant image (this may take a few minutes)...[/blue]")
            if not manager.pull_image():
                console.print("[red]Failed to pull Qdrant image[/red]")
                return
            console.print("[green]Qdrant image pulled successfully[/green]")
        
        # Start container
        service_url = manager.ensure_service_running(auto_pull=False)
        if service_url:
            console.print(f"[green]Qdrant service started at {service_url}[/green]")
            console.print(f"[blue]Update storage.qdrant.host in config/settings.yaml to: localhost[/blue]")
        else:
            console.print("[red]Failed to start Qdrant service[/red]")
    
    except ImportError as e:
        console.print(f"[red]Qdrant manager not available: {e}[/red]")
    except Exception as e:
        console.print(f"[red]Error starting Qdrant service: {e}[/red]")


@cli.command()
@click.pass_context
def stop_qdrant(ctx: click.Context) -> None:
    """Stop the Qdrant container service."""
    console.print("[blue]Stopping Qdrant service...[/blue]")
    
    try:
        from src.storage.qdrant_manager import QdrantManager
        
        manager = QdrantManager()
        
        if manager.stop_container():
            console.print("[green]Qdrant service stopped[/green]")
        else:
            console.print("[yellow]Qdrant service was not running[/yellow]")
    
    except ImportError as e:
        console.print(f"[red]Qdrant manager not available: {e}[/red]")
    except Exception as e:
        console.print(f"[red]Error stopping Qdrant service: {e}[/red]")


@cli.command()
@click.option("--year", type=int, required=True, help="Tax year")
@click.pass_context
def assist(ctx: click.Context, year: int) -> None:
    """Start interactive tax filing assistant."""
    from src.assistant.tax_assistant import TaxAssistant
    
    try:
        assistant = TaxAssistant(tax_year=year)
        assistant.run_interactive()
    except ImportError as e:
        console.print(f"[red]Assistant module not available: {e}[/red]")
    except Exception as e:
        console.print(f"[red]Error starting assistant: {e}[/red]")


@cli.command()
@click.option("--year", type=int, required=True, help="Tax year")
@click.option("--jurisdiction", "-j", type=click.Choice(["federal", "ca", "az"]), 
              required=True, help="Tax jurisdiction")
@click.option("--directory", "-d", type=click.Path(exists=True, file_okay=False), 
              required=True, help="Directory containing guidance files (.txt or .pdf)")
@click.pass_context
def load_guidance(ctx: click.Context, year: int, jurisdiction: str, directory: str) -> None:
    """Load tax guidance documents into Qdrant for RAG queries."""
    console.print(f"[blue]Loading tax guidance for {jurisdiction.upper()} {year}...[/blue]")
    
    try:
        from src.assistant.tax_guidance import TaxGuidanceLoader
        from src.storage.qdrant_manager import QdrantManager
        
        # Ensure Qdrant is running
        manager = QdrantManager()
        if not manager.is_container_running():
            console.print("[yellow]Starting Qdrant service...[/yellow]")
            if not manager.ensure_service_running(auto_pull=True):
                console.print("[red]Failed to start Qdrant service[/red]")
                return
        
        # Load guidance
        loader = TaxGuidanceLoader()
        guidance_dir = Path(directory)
        
        chunk_count = loader.load_directory(guidance_dir, jurisdiction, year)
        
        if chunk_count > 0:
            console.print(f"[green]✓ Loaded {chunk_count} guidance chunks from {guidance_dir}[/green]")
            console.print(f"[blue]The assistant can now use this information when answering questions.[/blue]")
        else:
            console.print("[yellow]No guidance files found or processed.[/yellow]")
            console.print("[yellow]Supported formats: .txt, .pdf[/yellow]")
    
    except ImportError as e:
        console.print(f"[red]Tax guidance module not available: {e}[/red]")
    except Exception as e:
        console.print(f"[red]Error loading guidance: {e}[/red]")


@cli.command()
@click.option("--year", type=int, required=True, help="Tax year")
@click.option("--jurisdiction", "-j", type=click.Choice(["federal", "ca", "az", "all"]), 
              default="all", help="Tax jurisdiction to filter by")
@click.argument("query")
@click.pass_context
def search_guidance(ctx: click.Context, year: int, jurisdiction: str, query: str) -> None:
    """Search tax guidance documents."""
    console.print(f"[blue]Searching tax guidance for: {query}[/blue]")
    
    try:
        from src.assistant.tax_guidance import TaxGuidanceLoader
        
        loader = TaxGuidanceLoader()
        
        # Convert "all" to None for jurisdiction filter
        jurisdiction_filter = None if jurisdiction == "all" else jurisdiction
        
        results = loader.search_guidance(
            query=query,
            jurisdiction=jurisdiction_filter,
            tax_year=year,
            limit=5,
        )
        
        if not results:
            console.print("[yellow]No guidance found matching your query.[/yellow]")
            console.print("[yellow]Try loading guidance first: python -m src.cli load-guidance[/yellow]")
            return
        
        console.print(f"[green]Found {len(results)} results:[/green]\n")
        
        for i, result in enumerate(results, 1):
            fields = result.get("extracted_fields", {})
            jurisdiction_label = fields.get("jurisdiction", "unknown").upper()
            doc_type = fields.get("document_type", "guidance")
            score = result.get("score", 0)
            
            console.print(Panel(
                f"{result.get('ocr_text', '')[:500]}...",
                title=f"[{i}] {jurisdiction_label} - {doc_type} (relevance: {score:.2f})",
                border_style="blue"
            ))
    
    except ImportError as e:
        console.print(f"[red]Tax guidance module not available: {e}[/red]")
    except Exception as e:
        console.print(f"[red]Error searching guidance: {e}[/red]")


@cli.command()
@click.option("--year", type=int, required=True, help="Tax year")
@click.option("--data-dir", type=click.Path(exists=True, file_okay=False), 
              default="data", help="Base data directory")
@click.pass_context
def load_all_guidance(ctx: click.Context, year: int, data_dir: str) -> None:
    """Auto-load tax guidance from standard directories (federal_docs, ca_docs, az_docs)."""
    console.print(f"[blue]Auto-loading tax guidance for {year}...[/blue]")
    
    try:
        from src.assistant.tax_guidance import auto_load_tax_guidance
        from pathlib import Path
        
        results = auto_load_tax_guidance(tax_year=year, data_dir=Path(data_dir))
        
        if not results:
            console.print("[yellow]No guidance directories found.[/yellow]")
            console.print("[yellow]Expected directories: data/federal_docs/, data/ca_docs/, data/az_docs/[/yellow]")
            return
        
        console.print("[green]Guidance loaded:[/green]")
        total = 0
        for jurisdiction, count in results.items():
            if count > 0:
                console.print(f"  {jurisdiction.upper()}: {count} chunks")
                total += count
        
        if total > 0:
            console.print(f"[green]✓ Total: {total} chunks loaded[/green]")
        else:
            console.print("[yellow]No guidance files found in directories.[/yellow]")
    
    except ImportError as e:
        console.print(f"[red]Tax guidance module not available: {e}[/red]")
    except Exception as e:
        console.print(f"[red]Error loading guidance: {e}[/red]")


@cli.command()
@click.option("--install", is_flag=True, help="Attempt to install missing dependencies")
def check_deps(install: bool) -> None:
    """Check and optionally install system dependencies."""
    from src.utils.dependencies import check_and_install_poppler, is_poppler_installed
    
    console.print("[bold]Checking system dependencies...[/bold]\n")
    
    # Check Poppler
    if is_poppler_installed():
        console.print("[green]✓ Poppler is installed[/green]")
    else:
        console.print("[red]✗ Poppler is NOT installed[/red]")
        console.print("  Poppler is required for PDF processing (tax guidance)")
        
        if install:
            console.print("\n[blue]Attempting to install Poppler...[/blue]")
            if check_and_install_poppler(auto_install=True):
                console.print("[green]✓ Poppler installed successfully![/green]")
                console.print("[yellow]Please restart your terminal for PATH changes to take effect.[/yellow]")
            else:
                console.print("[red]Failed to install Poppler automatically.[/red]")
                console.print("\nManual installation:")
                console.print("  Windows: choco install poppler")
                console.print("  macOS: brew install poppler")
                console.print("  Ubuntu/Debian: sudo apt-get install poppler-utils")
                console.print("\nDownload from:")
                console.print("  https://github.com/oschwartz10612/poppler-windows/releases/")
        else:
            console.print("\nRun with --install flag to attempt automatic installation:")
            console.print("  python -m src.cli check-deps --install")
    
    console.print("\n[bold]Python packages:[/bold]")
    
    # Check key Python packages
    packages = [
        ("pdf2image", "Required for PDF processing"),
        ("ollama", "Required for LLM extraction"),
        ("qdrant-client", "Required for vector storage"),
    ]
    
    for package, description in packages:
        try:
            __import__(package.replace("-", "_"))
            console.print(f"[green]✓ {package}[/green]")
        except ImportError:
            console.print(f"[red]✗ {package} - {description}[/red]")


if __name__ == "__main__":
    cli()