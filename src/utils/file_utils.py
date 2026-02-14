"""
File handling utilities for tax document processor.
"""

import hashlib
from pathlib import Path
from typing import Iterator, Optional


def ensure_dir(path: str | Path) -> Path:
    """
    Ensure a directory exists, creating it if necessary.
    
    Args:
        path: Directory path
    
    Returns:
        Path object for the directory
    """
    dir_path = Path(path)
    dir_path.mkdir(parents=True, exist_ok=True)
    return dir_path


def get_file_hash(file_path: str | Path, algorithm: str = "sha256") -> str:
    """
    Calculate the hash of a file.
    
    Args:
        file_path: Path to the file
        algorithm: Hash algorithm (sha256, md5, sha1)
    
    Returns:
        Hexadecimal hash string
    """
    path = Path(file_path)
    if not path.exists():
        raise FileNotFoundError(f"File not found: {file_path}")
    
    hash_func = hashlib.new(algorithm)
    
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            hash_func.update(chunk)
    
    return hash_func.hexdigest()


def list_documents(
    directory: str | Path,
    extensions: Optional[list[str]] = None,
    recursive: bool = True,
) -> Iterator[Path]:
    """
    List all documents in a directory.
    
    Args:
        directory: Directory to search
        extensions: File extensions to include (e.g., ['.pdf', '.png'])
        recursive: Whether to search recursively
    
    Yields:
        Path objects for each matching file
    """
    dir_path = Path(directory)
    
    if not dir_path.exists():
        return
    
    if extensions is None:
        extensions = [".pdf", ".png", ".jpg", ".jpeg", ".tiff", ".tif", ".bmp"]
    
    extensions = [ext.lower() for ext in extensions]
    
    if recursive:
        pattern = "**/*"
    else:
        pattern = "*"
    
    for file_path in dir_path.glob(pattern):
        if file_path.is_file() and file_path.suffix.lower() in extensions:
            yield file_path


def get_file_info(file_path: str | Path) -> dict:
    """
    Get information about a file.
    
    Args:
        file_path: Path to the file
    
    Returns:
        Dictionary with file information
    """
    path = Path(file_path)
    
    if not path.exists():
        raise FileNotFoundError(f"File not found: {file_path}")
    
    stat = path.stat()
    
    return {
        "name": path.name,
        "stem": path.stem,
        "extension": path.suffix.lower(),
        "size_bytes": stat.st_size,
        "size_mb": round(stat.st_size / (1024 * 1024), 2),
        "hash_sha256": get_file_hash(path),
        "absolute_path": str(path.absolute()),
        "parent_dir": str(path.parent),
    }


def copy_file(
    source: str | Path,
    destination: str | Path,
    overwrite: bool = False,
) -> Path:
    """
    Copy a file to a destination.
    
    Args:
        source: Source file path
        destination: Destination file or directory path
        overwrite: Whether to overwrite existing files
    
    Returns:
        Path to the copied file
    """
    import shutil
    
    src_path = Path(source)
    dst_path = Path(destination)
    
    if not src_path.exists():
        raise FileNotFoundError(f"Source file not found: {source}")
    
    # If destination is a directory, use the source filename
    if dst_path.is_dir():
        dst_path = dst_path / src_path.name
    
    if dst_path.exists() and not overwrite:
        raise FileExistsError(f"Destination file exists: {destination}")
    
    # Ensure parent directory exists
    dst_path.parent.mkdir(parents=True, exist_ok=True)
    
    shutil.copy2(src_path, dst_path)
    
    return dst_path


def move_file(
    source: str | Path,
    destination: str | Path,
    overwrite: bool = False,
) -> Path:
    """
    Move a file to a destination.
    
    Args:
        source: Source file path
        destination: Destination file or directory path
        overwrite: Whether to overwrite existing files
    
    Returns:
        Path to the moved file
    """
    import shutil
    
    src_path = Path(source)
    dst_path = Path(destination)
    
    if not src_path.exists():
        raise FileNotFoundError(f"Source file not found: {source}")
    
    # If destination is a directory, use the source filename
    if dst_path.is_dir():
        dst_path = dst_path / src_path.name
    
    if dst_path.exists() and not overwrite:
        raise FileExistsError(f"Destination file exists: {destination}")
    
    # Ensure parent directory exists
    dst_path.parent.mkdir(parents=True, exist_ok=True)
    
    shutil.move(str(src_path), str(dst_path))
    
    return dst_path


def read_text_file(file_path: str | Path, encoding: str = "utf-8") -> str:
    """
    Read a text file.
    
    Args:
        file_path: Path to the file
        encoding: File encoding
    
    Returns:
        File contents as string
    """
    path = Path(file_path)
    
    if not path.exists():
        raise FileNotFoundError(f"File not found: {file_path}")
    
    with open(path, "r", encoding=encoding) as f:
        return f.read()


def write_text_file(
    file_path: str | Path,
    content: str,
    encoding: str = "utf-8",
) -> Path:
    """
    Write content to a text file.
    
    Args:
        file_path: Path to the file
        content: Content to write
        encoding: File encoding
    
    Returns:
        Path to the written file
    """
    path = Path(file_path)
    
    # Ensure parent directory exists
    path.parent.mkdir(parents=True, exist_ok=True)
    
    with open(path, "w", encoding=encoding) as f:
        f.write(content)
    
    return path


def write_json_file(
    file_path: str | Path,
    data: dict | list,
    indent: int = 2,
) -> Path:
    """
    Write data to a JSON file.
    
    Args:
        file_path: Path to the file
        data: Data to write
        indent: JSON indentation
    
    Returns:
        Path to the written file
    """
    import json
    
    path = Path(file_path)
    
    # Ensure parent directory exists
    path.parent.mkdir(parents=True, exist_ok=True)
    
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=indent, ensure_ascii=False)
    
    return path


def read_json_file(file_path: str | Path) -> dict | list:
    """
    Read a JSON file.
    
    Args:
        file_path: Path to the file
    
    Returns:
        Parsed JSON data
    """
    import json
    
    path = Path(file_path)
    
    if not path.exists():
        raise FileNotFoundError(f"File not found: {file_path}")
    
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)