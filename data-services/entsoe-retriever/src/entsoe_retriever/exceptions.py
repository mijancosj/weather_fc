class EntsoeError(Exception):
    """Base class for all entsoe-retriever errors."""


class EntsoeConfigurationError(EntsoeError):
    """The client is missing configuration it needs to make a request (e.g. no API token)."""


class EntsoeApiError(EntsoeError):
    """The ENTSO-E API returned an error response."""

    def __init__(self, status_code: int, body: str) -> None:
        self.status_code = status_code
        self.body = body
        super().__init__(f"ENTSO-E API error {status_code}: {body[:500]}")


class EntsoeParseError(EntsoeError):
    """The XML response from ENTSO-E could not be parsed into domain models."""
