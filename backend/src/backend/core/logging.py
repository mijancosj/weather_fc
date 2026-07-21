import logging
import sys

import structlog


def configure_logging(environment: str) -> None:
    # Reconfigure at runtime rather than relying on PYTHONUTF8 (which only
    # takes effect at interpreter startup, so it can't help scripts already
    # running): a legacy Windows console defaults stdout/stderr to cp1252,
    # and both FastAPI's rich-based CLI banner and structlog's ConsoleRenderer
    # (which auto-upgrades to rich's traceback formatting when rich is
    # installed) crash with UnicodeEncodeError the moment a log message
    # contains a character cp1252 can't represent — confirmed to happen even
    # inside an exception handler, which is a particularly bad time to crash.
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")

    logging.basicConfig(stream=sys.stdout, level=logging.INFO, format="%(message)s")
    structlog.configure(
        processors=[
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.add_log_level,
            structlog.processors.JSONRenderer()
            if environment == "production"
            else structlog.dev.ConsoleRenderer(),
        ],
        logger_factory=structlog.stdlib.LoggerFactory(),
    )
