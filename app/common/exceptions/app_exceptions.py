class EskanError(Exception):
    """Base application error."""


class InputValidationError(EskanError):
    """Recoverable input validation issue."""


class PdfProcessingError(EskanError):
    """Raised when page or document processing fails."""
