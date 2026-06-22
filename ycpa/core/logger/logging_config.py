import logging
import os
from logging.handlers import RotatingFileHandler, TimedRotatingFileHandler
from pathlib import Path

from rich.logging import RichHandler
from rich.traceback import install as install_rich_traceback

from ycpa.core.config import get_settings
from ycpa.core.logger.visual_logger import DatabaseHighlighter, console

_NOISY_LOGGERS = (
    "urllib3", "boto3", "botocore", "s3transfer",
    "uvicorn.access", "httpcore", "httpx",
)


class WinSafeTimedRotatingFileHandler(TimedRotatingFileHandler):
    """Handles Windows file-locking issue during log rotation (WinError 32)."""

    def rotate(self, source, dest):
        if os.path.exists(dest):
            try:
                os.remove(dest)
            except PermissionError:
                return
        try:
            os.rename(source, dest)
        except PermissionError:
            pass

    def doRollover(self):
        try:
            super().doRollover()
        except PermissionError:
            pass


def setup_logging() -> None:
    settings = get_settings()
    level_str = settings.LOG_LEVEL.upper()
    level     = getattr(logging, level_str, logging.INFO)
    log_dir   = Path(settings.LOG_DIR)
    log_dir.mkdir(parents=True, exist_ok=True)

    install_rich_traceback(show_locals=settings.DEBUG, width=120, extra_lines=3)

    root = logging.getLogger()
    root.setLevel(level)
    root.handlers.clear()
    logging.getLogger("passlib").setLevel(logging.ERROR)

    root.addHandler(RichHandler(
        console=console,
        level=level,
        rich_tracebacks=True,
        tracebacks_show_locals=settings.DEBUG,
        markup=True,
        highlighter=DatabaseHighlighter(),
        keywords=[],
        show_time=True,
        show_level=True,
        show_path=settings.DEBUG,

    ))

    fmt = logging.Formatter(
        "%(asctime)s | %(levelname)-8s | %(name)s | [%(request_id)s] | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    app_fh = RotatingFileHandler(
        log_dir / "ycpa.log",
        maxBytes=10 * 1024 * 1024,
        backupCount=5,
        encoding="utf-8",
    )
    app_fh.setLevel(level)
    app_fh.setFormatter(fmt)
    app_fh.addFilter(_RequestIdFilter())
    root.addHandler(app_fh)

    err_fh = WinSafeTimedRotatingFileHandler(
        log_dir / "error.log",
        when="midnight", interval=1, backupCount=30, encoding="utf-8",
        delay=True,
    )
    err_fh.setLevel(logging.ERROR)
    err_fh.setFormatter(fmt)
    err_fh.addFilter(_RequestIdFilter())
    root.addHandler(err_fh)

    if settings.ENVIRONMENT != "development":
        json_fh = RotatingFileHandler(
            log_dir / "ycpa.json.log",
            maxBytes=10 * 1024 * 1024, backupCount=5, encoding="utf-8",
        )
        json_fh.setLevel(level)
        json_fh.setFormatter(_JsonFormatter(settings))
        root.addHandler(json_fh)

    access_fh = WinSafeTimedRotatingFileHandler(
        log_dir / "access.log",
        when="midnight", interval=1, backupCount=7, encoding="utf-8",
        delay=True,
    )
    access_fh.setFormatter(logging.Formatter(
        "%(asctime)s | %(message)s", datefmt="%Y-%m-%d %H:%M:%S"
    ))
    access_log = logging.getLogger("access")
    access_log.setLevel(logging.INFO)
    access_log.addHandler(access_fh)
    access_log.propagate = False

    for name in _NOISY_LOGGERS:
        logging.getLogger(name).setLevel(logging.WARNING)

    from ycpa.core.database.engine import silence_sqlalchemy
    silence_sqlalchemy()

    logging.getLogger(__name__).info(
        f"Logging ready | level={level_str} | env={settings.ENVIRONMENT} | "
        f"dir={log_dir} | sql_logs={'on' if settings.ENVIRONMENT == 'development' else 'off'}"
    )


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)


class _RequestIdFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = getattr(record, "request_id", "-")
        return True


class _JsonFormatter(logging.Formatter):

    def __init__(self, settings):
        super().__init__()
        self._env     = settings.ENVIRONMENT
        self._service = settings.APP_NAME

    def format(self, record: logging.LogRecord) -> str:
        import json
        from datetime import datetime, timezone

        data = {
            "ts":          datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat(),
            "level":       record.levelname,
            "logger":      record.name,
            "msg":         record.getMessage(),
            "module":      record.module,
            "fn":          record.funcName,
            "line":        record.lineno,
            "env":         self._env,
            "service":     self._service,
            "request_id":  getattr(record, "request_id",  "-"),
            "user_id":     getattr(record, "user_id",     None),
            "correlation": getattr(record, "correlation_id", None),
        }

        if record.exc_info:
            data["exc"] = {
                "type":    record.exc_info[0].__name__ if record.exc_info[0] else None,
                "msg":     str(record.exc_info[1]),
                "tb":      self.formatException(record.exc_info),
            }

        return json.dumps(data, default=str)