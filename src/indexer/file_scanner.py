import os
from typing import List
from src.config import SUPPORTED_WORD_EXTENSIONS
from src.utils.logger import get_logger

logger = get_logger("file_scanner")

from src.utils.file_utils import canonical_path, to_long_path

class FileScanner:
    """Recursively scans directories for supported Word documents."""

    def scan_directory(self, folder_path: str, recursive: bool = True) -> List[str]:
        """Returns canonical absolute filepaths of all Word files in directory."""
        word_files = []
        target_folder = to_long_path(folder_path)
        if not os.path.exists(target_folder) and not os.path.exists(folder_path):
            logger.warning(f"Directory path does not exist: {folder_path}")
            return word_files

        try:
            if recursive:
                for root, _, files in os.walk(target_folder):
                    clean_root = root[4:] if root.startswith('\\\\?\\') else root
                    for file in files:
                        ext = os.path.splitext(file)[1].lower()
                        if ext in SUPPORTED_WORD_EXTENSIONS and not file.startswith("~$"):
                            word_files.append(canonical_path(os.path.join(clean_root, file)))
            else:
                for file in os.listdir(target_folder):
                    full_p = os.path.join(folder_path, file)
                    long_p = to_long_path(full_p)
                    if os.path.isfile(long_p) or os.path.isfile(full_p):
                        ext = os.path.splitext(file)[1].lower()
                        if ext in SUPPORTED_WORD_EXTENSIONS and not file.startswith("~$"):
                            word_files.append(canonical_path(full_p))
        except Exception as e:
            logger.error(f"Error scanning directory {folder_path}: {e}")

        logger.info(f"Scanned {folder_path}: Found {len(word_files)} Word document(s).")
        return word_files
