"""BetterMarkItDown - MarkItDown plus a vision layer for PDFs whose content is pictures."""

__version__ = "1.0.0"

from .config import Options, Result
from .core import convert

__all__ = ["Options", "Result", "convert", "__version__"]
