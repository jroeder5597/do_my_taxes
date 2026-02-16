"""
Unified configuration loader for tax document processor.
Loads settings from YAML file (config/settings.yaml).
"""

from pathlib import Path
from typing import Any, Optional

from pydantic import BaseModel

from src.utils import get_logger

logger = get_logger(__name__)

# Try to import yaml
try:
    import yaml
    YAML_AVAILABLE = True
except ImportError:
    YAML_AVAILABLE = False
    logger.warning("PyYAML not installed. YAML configuration will not be available.")


class PathsConfig(BaseModel):
    """Paths configuration."""
    raw_documents: str = "data/raw_documents"
    processed: str = "data/processed"
    exports: str = "data/exports"
    database: str = "db/taxes.db"
    logs: str = "logs"


class OcrConfig(BaseModel):
    """OCR configuration."""
    service_url: str = "http://127.0.0.1:5000"
    languages: list[str] = ["eng"]
    dpi: int = 300
    pdf_to_image_dpi: int = 300


class OllamaOptions(BaseModel):
    """Ollama generation options."""
    temperature: float = 0.1
    num_ctx: int = 8192
    num_predict: int = 4096


class OllamaConfig(BaseModel):
    """Ollama configuration."""
    base_url: str = "http://localhost:11434"
    model: str = "qwen3:8b"
    extraction_options: OllamaOptions = OllamaOptions()
    assistant_options: OllamaOptions = OllamaOptions(temperature=0.3, num_ctx=16384, num_predict=2048)


class LlmConfig(BaseModel):
    """LLM configuration."""
    provider: str = "ollama"
    ollama: OllamaConfig = OllamaConfig()


class SqliteConfig(BaseModel):
    """SQLite configuration."""
    database: str = "db/taxes.db"


class QdrantConfig(BaseModel):
    """Qdrant configuration."""
    host: str = "localhost"
    port: int = 6333
    collection: str = "tax_documents"
    embedding_model: str = "local"
    vector_size: int = 384


class StorageConfig(BaseModel):
    """Storage configuration."""
    sqlite: SqliteConfig = SqliteConfig()
    qdrant: QdrantConfig = QdrantConfig()


class ScreenAssistantConfig(BaseModel):
    """Screen assistant configuration."""
    capture_hotkey: str = "ctrl+shift+s"
    poll_interval: int = 2


class LoggingConfig(BaseModel):
    """Logging configuration."""
    level: str = "INFO"
    format: str = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    file: str = "logs/tax_processor.log"


class ProjectConfig(BaseModel):
    """Project metadata."""
    name: str = "Tax Document Processor"
    version: str = "1.0.0"
    description: str = "OCR and LLM-based tax document processing system"


class Settings(BaseModel):
    """Main settings container."""
    project: ProjectConfig = ProjectConfig()
    paths: PathsConfig = PathsConfig()
    ocr: OcrConfig = OcrConfig()
    llm: LlmConfig = LlmConfig()
    storage: StorageConfig = StorageConfig()
    screen_assistant: ScreenAssistantConfig = ScreenAssistantConfig()
    logging: LoggingConfig = LoggingConfig()


class ConfigLoader:
    """
    Configuration loader that reads settings from YAML file.
    
    The configuration is loaded from config/settings.yaml which is the
    single source of truth for all application settings.
    """
    
    DEFAULT_CONFIG_PATH = "config/settings.yaml"
    
    _instance: Optional["ConfigLoader"] = None
    _settings: Optional[Settings] = None
    
    def __new__(cls) -> "ConfigLoader":
        """Singleton pattern to ensure single configuration instance."""
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance
    
    def __init__(self):
        """Initialize the configuration loader."""
        if self._settings is None:
            self._load_config()
    
    def _load_config(self) -> None:
        """Load configuration from YAML file."""
        # Start with defaults
        config_dict: dict[str, Any] = {}
        
        # Load YAML configuration
        yaml_path = Path(self.DEFAULT_CONFIG_PATH)
        if yaml_path.exists() and YAML_AVAILABLE:
            try:
                with open(yaml_path, "r") as f:
                    config_dict = yaml.safe_load(f) or {}
                logger.debug(f"Loaded configuration from {yaml_path}")
            except Exception as e:
                logger.warning(f"Failed to load {yaml_path}: {e}")
        else:
            if not YAML_AVAILABLE:
                logger.warning("PyYAML not available, using defaults")
            else:
                logger.warning(f"Configuration file {yaml_path} not found, using defaults")
        
        # Create settings object
        self._settings = Settings(**config_dict)
        logger.info("Configuration loaded successfully")
    
    @property
    def settings(self) -> Settings:
        """Get the current settings."""
        if self._settings is None:
            self._load_config()
        return self._settings
    
    def reload(self) -> None:
        """Reload configuration from file."""
        self._settings = None
        self._load_config()


# Global configuration instance
_config: Optional[ConfigLoader] = None


def get_config() -> ConfigLoader:
    """
    Get the global configuration loader instance.
    
    Returns:
        ConfigLoader singleton instance
    """
    global _config
    if _config is None:
        _config = ConfigLoader()
    return _config


def get_settings() -> Settings:
    """
    Get the current settings object.
    
    Returns:
        Settings object with merged configuration
    """
    return get_config().settings


def reload_config() -> None:
    """Reload configuration from files."""
    global _config
    if _config is not None:
        _config.reload()
    else:
        _config = ConfigLoader()