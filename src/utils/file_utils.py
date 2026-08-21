import os
import sys
import hashlib
import subprocess
from pathlib import Path
from typing import Optional
from src.utils.logger import get_logger

logger = get_logger("file_utils")

def to_long_path(path: str) -> str:
    """Formats path with Windows extended-length prefix (\\\\?\\) if needed on Windows."""
    if not path:
        return path
    if os.name == 'nt' and not path.startswith('\\\\?\\'):
        abs_p = os.path.abspath(path)
        if not abs_p.startswith('\\\\?\\'):
            return f"\\\\?\\{abs_p}"
    return path

def canonical_path(path: str) -> str:
    """Returns a normalized absolute path (without \\\\?\\ prefix) used as the
    stable unique key for the search index, so the same physical file always
    maps to the same key regardless of the process working directory."""
    if not path:
        return path
    raw = path[4:] if path.startswith('\\\\?\\') else path
    try:
        resolved = os.path.realpath(raw)
    except Exception:
        resolved = os.path.abspath(raw)
    resolved = os.path.normpath(resolved)
    if os.name == 'nt':
        resolved = os.path.normcase(resolved)
    return resolved

def compute_file_hash(filepath: str, block_size: int = 65536) -> str:
    """Computes SHA-256 hash of a file for cache invalidation."""
    hasher = hashlib.sha256()
    target_p = to_long_path(filepath)
    try:
        with open(target_p, "rb") as f:
            for chunk in iter(lambda: f.read(block_size), b""):
                hasher.update(chunk)
        return hasher.hexdigest()
    except Exception as e:
        logger.error(f"Error computing hash for {filepath}: {e}")
        return ""

def format_file_size(size_bytes: int) -> str:
    """Formats raw byte size into human readable string."""
    if size_bytes <= 0:
        return "0 B"
    units = ["B", "KB", "MB", "GB", "TB"]
    i = 0
    size = float(size_bytes)
    while size >= 1024 and i < len(units) - 1:
        size /= 1024.0
        i += 1
    return f"{size:.1f} {units[i]}"

def open_document_in_default_app(filepath: str) -> bool:
    """Opens a document in the operating system's default application."""
    if not os.path.exists(filepath):
        logger.error(f"File not found: {filepath}")
        return False

    try:
        if sys.platform.startswith("win"):
            os.startfile(os.path.normpath(filepath))
        elif sys.platform == "darwin":
            subprocess.run(["open", filepath], check=True)
        else:
            subprocess.run(["xdg-open", filepath], check=True)
        return True
    except Exception as e:
        logger.error(f"Failed to open document {filepath}: {e}")
        return False
