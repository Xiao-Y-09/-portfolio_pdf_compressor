"""Custom exceptions for the compressor package."""


class CompressorError(Exception):
    """Base class for all compressor errors."""


class PDFParseError(CompressorError):
    """Raised when the input PDF cannot be opened or scanned."""


class ClassificationError(CompressorError):
    """Raised when hero/process classification fails."""


class CompressionError(CompressorError):
    """Raised when the target size cannot be reached."""
