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
from src.ocr import PDFProcessor, ImageOCR, DocumentClassifier
from src.extraction import LLMExtractor, DataValidator

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
    image_ocr = None  # Lazy load
    classifier = DocumentClassifier()
    llm_extractor = None  # Lazy load
    validator = DataValidator(year)
    
    # Log OCR provider being used
    ocr_provider = settings.ocr.provider
    console.print(f"[blue]Using OCR provider: {ocr_provider}[/blue]")
    
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
                
                # Initialize OCR processor based on configuration
                if image_ocr is None:
                    if ocr_provider == "ollama_vision":
                        from src.ocr.ollama_vision_ocr import OllamaVisionOCR
                        image_ocr = OllamaVisionOCR(
                            model=settings.ocr.ollama_vision.model,
                            base_url=settings.llm.ollama.base_url,
                            temperature=settings.ocr.ollama_vision.temperature,
                            dpi=settings.ocr.dpi,
                        )
                    else:
                        image_ocr = ImageOCR()
                
                if file_path.suffix.lower() == ".pdf":
                    text = pdf_processor.extract_text(file_path)
                    
                    # If no text, use OCR
                    if not text:
                        text = image_ocr.process_pdf(file_path)
                else:
                    text = image_ocr.process_image(file_path)
                
                # Update OCR text
                db.update_document_ocr_text(doc.id, text)
                
                # Classify document
                doc_type, confidence = classifier.classify(text)
                
                # Extract data using LLM
                if doc_type in [DocumentType.W2, DocumentType.FORM_1099_INT, DocumentType.FORM_1099_DIV]:
                    if llm_extractor is None:
                        settings = get_settings()
                        llm_extractor = LLMExtractor(
                            model=settings.llm.ollama.model,
                            base_url=settings.llm.ollama.base_url,
                        )
                    
                    if doc_type == DocumentType.W2:
                        data = llm_extractor.extract_w2(text, doc.id)
                        if data:
                            is_valid, errors = validator.validate_w2(data)
                            if not is_valid:
                                console.print(f"[red]W-2 validation failed: {errors}[/red]")
                            else:
                                db.save_w2_data(data)
                                console.print(f"[green]Extracted W-2 data from {file_path.name}[/green]")
                    
                    elif doc_type == DocumentType.FORM_1099_INT:
                        data = llm_extractor.extract_1099_int(text, doc.id)
                        if data:
                            is_valid, errors = validator.validate_1099_int(data)
                            if not is_valid:
                                console.print(f"[red]1099-INT validation failed: {errors}[/red]")
                            else:
                                db.save_1099_int_data(data)
                                console.print(f"[green]Extracted 1099-INT data from {file_path.name}[/green]")
                    
                    elif doc_type == DocumentType.FORM_1099_DIV:
                        data = llm_extractor.extract_1099_div(text, doc.id)
                        if data:
                            is_valid, errors = validator.validate_1099_div(data)
                            if not is_valid:
                                console.print(f"[red]1099-DIV validation failed: {errors}[/red]")
                            else:
                                db.save_1099_div_data(data)
                                console.print(f"[green]Extracted 1099-DIV data from {file_path.name}[/green]")
                
                else:
                    console.print(f"[yellow]Unsupported document type: {doc_type.value}[/yellow]")
                
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
        settings = get_settings()
        extractor = LLMExtractor(
            model=settings.llm.ollama.model,
            base_url=settings.llm.ollama.base_url,
        )
        
        if extractor.check_connection():
            console.print("[green]✓ Ollama is running and accessible[/green]")
            
            # Try a simple query
            response = extractor.chat([
                {"role": "user", "content": "Say 'hello' in one word."}
            ])
            console.print(f"[green]✓ Model responded: {response[:50]}...[/green]")
        else:
            console.print("[red]✗ Cannot connect to Ollama[/red]")
            console.print("[yellow]Make sure Ollama is running: ollama serve[/yellow]")
    
    except Exception as e:
        console.print(f"[red]✗ Error: {e}[/red]")


@cli.command()
@click.pass_context
def check_ollama_vision(ctx: click.Context) -> None:
    """Check Ollama Vision OCR model availability."""
    console.print("[blue]Checking Ollama Vision OCR...[/blue]")
    
    try:
        settings = get_settings()
        
        # Check if using Ollama Vision OCR
        if settings.ocr.provider != "ollama_vision":
            console.print(f"[yellow]⚠ OCR provider is set to '{settings.ocr.provider}', not 'ollama_vision'[/yellow]")
            console.print("[blue]Update ocr.provider in config/settings.yaml to use Ollama Vision[/blue]")
        
        from src.ocr.ollama_vision_ocr import OllamaVisionOCR
        
        ocr = OllamaVisionOCR(
            model=settings.ocr.ollama_vision.model,
            base_url=settings.llm.ollama.base_url,
        )
        
        # Check connection
        if ocr.check_connection():
            console.print("[green]✓ Ollama is running and accessible[/green]")
            
            # Check model
            model_status = ocr.check_model()
            
            if model_status["model_available"]:
                console.print(f"[green]✓ Vision model '{settings.ocr.ollama_vision.model}' is available[/green]")
            else:
                console.print(f"[red]✗ Vision model '{settings.ocr.ollama_vision.model}' not found[/red]")
                console.print(f"[blue]Available models: {', '.join(model_status.get('available_models', []))}[/blue]")
                console.print(f"[yellow]Pull the model with: ollama pull {settings.ocr.ollama_vision.model}[/yellow]")
            
            # Show configuration
            table = Table(title="Ollama Vision OCR Configuration")
            table.add_column("Setting", style="cyan")
            table.add_column("Value", style="green")
            
            table.add_row("Provider", settings.ocr.provider)
            table.add_row("Model", settings.ocr.ollama_vision.model)
            table.add_row("Base URL", settings.llm.ollama.base_url)
            table.add_row("Temperature", str(settings.ocr.ollama_vision.temperature))
            table.add_row("DPI", str(settings.ocr.dpi))
            
            console.print(table)
        else:
            console.print("[red]✗ Cannot connect to Ollama[/red]")
            console.print("[yellow]Make sure Ollama is running: ollama serve[/yellow]")
    
    except ImportError as e:
        console.print(f"[red]✗ Ollama Vision OCR not available: {e}[/red]")
    except Exception as e:
        console.print(f"[red]✗ Error: {e}[/red]")


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
            console.print("[yellow]Start Qdrant with: docker run -p 6333:6333 qdrant/qdrant[/yellow]")
    
    except Exception as e:
        console.print(f"[red]✗ Error: {e}[/red]")


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
@click.pass_context
def check_ocr(ctx: click.Context) -> None:
    """Check OCR service status."""
    console.print("[blue]Checking OCR service status...[/blue]")
    
    try:
        from src.ocr.docker_manager import get_ocr_status
        
        status = get_ocr_status()
        
        # Create status table
        table = Table(title="OCR Service Status")
        table.add_column("Component", style="cyan")
        table.add_column("Status", style="green")
        
        table.add_row(
            "Podman Available",
            "✓ Yes" if status["podman_available"] else "✗ No"
        )
        table.add_row(
            "Image Built",
            "✓ Yes" if status["image_built"] else "✗ No"
        )
        table.add_row(
            "Container Running",
            "✓ Yes" if status["container_running"] else "✗ No"
        )
        table.add_row(
            "Service Healthy",
            "✓ Yes" if status["service_healthy"] else "✗ No"
        )
        table.add_row(
            "Service URL",
            status["service_url"] or "N/A"
        )
        
        console.print(table)
        
        if not status["podman_available"]:
            console.print("[yellow]Podman is not available. Install Podman to use containerized OCR.[/yellow]")
        elif not status["image_built"]:
            console.print("[yellow]OCR image not built. Run: python -m src.main build-ocr[/yellow]")
        elif not status["container_running"]:
            console.print("[yellow]OCR container not running. Run: python -m src.main start-ocr[/yellow]")
        elif not status["service_healthy"]:
            console.print("[yellow]OCR service is not healthy. Check container logs.[/yellow]")
        else:
            console.print("[green]OCR service is running and healthy![/green]")
    
    except ImportError as e:
        console.print(f"[red]Podman manager not available: {e}[/red]")
    except Exception as e:
        console.print(f"[red]Error checking OCR status: {e}[/red]")


@cli.command()
@click.option("--port", type=int, default=5000, help="Port for OCR service")
@click.pass_context
def start_ocr(ctx: click.Context, port: int) -> None:
    """Start the OCR container service."""
    console.print("[blue]Starting OCR service...[/blue]")
    
    try:
        from src.ocr.docker_manager import PodmanManager
        
        manager = PodmanManager(port=port)
        
        if not manager.is_podman_available():
            console.print("[red]✗ Podman is not available[/red]")
            console.print("[yellow]Install Podman to use containerized OCR, or use local Tesseract.[/yellow]")
            return
        
        # Build image if needed
        if not manager.is_image_built():
            console.print("[blue]Building OCR image (this may take a few minutes)...[/blue]")
            if not manager.build_image():
                console.print("[red]✗ Failed to build OCR image[/red]")
                return
            console.print("[green]✓ OCR image built successfully[/green]")
        
        # Start container
        service_url = manager.ensure_service_running(auto_build=False)
        if service_url:
            console.print(f"[green]✓ OCR service started at {service_url}[/green]")
            console.print(f"[blue]Update ocr.service_url in config/settings.yaml to: {service_url}[/blue]")
        else:
            console.print("[red]✗ Failed to start OCR service[/red]")
    
    except ImportError as e:
        console.print(f"[red]Podman manager not available: {e}[/red]")
    except Exception as e:
        console.print(f"[red]Error starting OCR service: {e}[/red]")


@cli.command()
@click.pass_context
def stop_ocr(ctx: click.Context) -> None:
    """Stop the OCR container service."""
    console.print("[blue]Stopping OCR service...[/blue]")
    
    try:
        from src.ocr.docker_manager import PodmanManager
        
        manager = PodmanManager()
        
        if manager.stop_container():
            console.print("[green]✓ OCR service stopped[/green]")
        else:
            console.print("[yellow]OCR service was not running[/yellow]")
    
    except ImportError as e:
        console.print(f"[red]Podman manager not available: {e}[/red]")
    except Exception as e:
        console.print(f"[red]Error stopping OCR service: {e}[/red]")


@cli.command()
@click.pass_context
def build_ocr(ctx: click.Context) -> None:
    """Build the OCR Podman image."""
    console.print("[blue]Building OCR Podman image...[/blue]")
    
    try:
        from src.ocr.docker_manager import PodmanManager
        
        manager = PodmanManager()
        
        if not manager.is_podman_available():
            console.print("[red]✗ Podman is not available[/red]")
            return
        
        if manager.build_image():
            console.print("[green]✓ OCR image built successfully[/green]")
        else:
            console.print("[red]✗ Failed to build OCR image[/red]")
    
    except ImportError as e:
        console.print(f"[red]Podman manager not available: {e}[/red]")
    except Exception as e:
        console.print(f"[red]Error building OCR image: {e}[/red]")


if __name__ == "__main__":
    cli()