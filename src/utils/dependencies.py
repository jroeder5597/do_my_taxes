"""
System dependency checker and installer.
Handles automatic installation of required system dependencies.
"""

import shutil
import subprocess
from pathlib import Path
from typing import Optional

from src.utils import get_logger

logger = get_logger(__name__)


def is_poppler_installed() -> bool:
    """Check if Poppler is installed and accessible."""
    return shutil.which("pdftoppm") is not None


def install_poppler_windows() -> bool:
    """
    Install Poppler on Windows using chocolatey.
    
    Returns:
        True if installation succeeded, False otherwise
    """
    try:
        # Check if chocolatey is available
        if not shutil.which("choco"):
            logger.error("Chocolatey not found. Please install chocolatey first:")
            logger.error("  https://chocolatey.org/install")
            return False
        
        logger.info("Installing Poppler via chocolatey...")
        logger.info("This may take a few minutes...")
        
        # Run chocolatey install
        result = subprocess.run(
            ["choco", "install", "poppler", "-y"],
            capture_output=True,
            text=True,
            timeout=300,  # 5 minute timeout
        )
        
        if result.returncode == 0:
            logger.info("Poppler installed successfully!")
            logger.info("Please restart your terminal/command prompt for PATH changes to take effect.")
            return True
        else:
            logger.error(f"Failed to install Poppler: {result.stderr}")
            return False
            
    except subprocess.TimeoutExpired:
        logger.error("Poppler installation timed out")
        return False
    except Exception as e:
        logger.error(f"Error installing Poppler: {e}")
        return False


def check_and_install_poppler(auto_install: bool = True) -> bool:
    """
    Check if Poppler is installed, optionally install it.
    
    Args:
        auto_install: Automatically attempt installation if not found
        
    Returns:
        True if Poppler is available (or was installed), False otherwise
    """
    if is_poppler_installed():
        return True
    
    logger.warning("Poppler is not installed (required for PDF processing)")
    
    if not auto_install:
        return False
    
    # Try to install based on platform
    import platform
    system = platform.system()
    
    if system == "Windows":
        if install_poppler_windows():
            # Recheck after installation
            return is_poppler_installed()
    elif system == "Darwin":  # macOS
        logger.info("Please install Poppler using Homebrew:")
        logger.info("  brew install poppler")
    elif system == "Linux":
        logger.info("Please install Poppler using your package manager:")
        logger.info("  Ubuntu/Debian: sudo apt-get install poppler-utils")
        logger.info("  Fedora: sudo dnf install poppler-utils")
    
    return False


def ensure_poppler_available() -> bool:
    """
    Ensure Poppler is available for PDF processing.
    Returns True if available, logs helpful message if not.
    """
    if is_poppler_installed():
        return True
    
    logger.error("=" * 60)
    logger.error("POPPLER NOT FOUND")
    logger.error("=" * 60)
    logger.error("")
    logger.error("PDF processing requires Poppler to be installed.")
    logger.error("")
    logger.error("To install automatically, run this command as Administrator:")
    logger.error("  choco install poppler")
    logger.error("")
    logger.error("Or download from:")
    logger.error("  https://github.com/oschwartz10612/poppler-windows/releases/")
    logger.error("")
    logger.error("After installation, restart your terminal.")
    logger.error("=" * 60)
    
    return False
