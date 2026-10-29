"""Small filesystem helpers shared by the routes."""

import gc
import shutil
from pathlib import Path


def remove_folder(path: Path) -> None:
    """Remove a folder, retrying once after a garbage collection.

    On Windows a file that is still open cannot be deleted. An image or PDF
    object that is no longer referenced but not yet freed can be the holder, so
    collecting garbage and trying again usually clears it. Whatever still
    survives is left for the sweeper.
    """
    shutil.rmtree(path, ignore_errors=True)
    if path.exists():
        gc.collect()
        shutil.rmtree(path, ignore_errors=True)