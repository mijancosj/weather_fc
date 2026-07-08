class ElexonError(Exception):
    """Base class for all elexon-retriever errors."""


class ElexonApiError(ElexonError):
    """The Elexon API returned an error response."""

    def __init__(self, status_code: int, body: str) -> None:
        self.status_code = status_code
        self.body = body
        super().__init__(f"Elexon API error {status_code}: {body[:500]}")
