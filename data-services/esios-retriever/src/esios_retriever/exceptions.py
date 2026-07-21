class EsiosError(Exception):
    """Base class for all esios-retriever errors."""


class EsiosConfigurationError(EsiosError):
    """The client is missing configuration it needs to make a request (e.g. no API token)."""


class EsiosApiError(EsiosError):
    """The ESIOS API returned an error response."""

    def __init__(self, status_code: int, body: str) -> None:
        self.status_code = status_code
        self.body = body
        super().__init__(f"ESIOS API error {status_code}: {body[:500]}")


class EsiosParseError(EsiosError):
    """The JSON response from ESIOS could not be parsed into domain models."""
