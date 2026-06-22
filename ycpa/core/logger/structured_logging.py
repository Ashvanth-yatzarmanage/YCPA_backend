import json
import logging
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict  # noqa: UP035

from ycpa.core.config import get_settings

settings = get_settings()


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        log_data: dict[str, Any] = {
            "timestamp": datetime.utcfromtimestamp(record.created).isoformat() + "Z",
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "module": record.module,
            "function": record.funcName,
            "line": record.lineno,
        }

        if hasattr(record, 'request_id'):
            log_data["request_id"] = record.request_id

        if hasattr(record, 'user_id'):
            log_data["user_id"] = record.user_id

        if hasattr(record, 'correlation_id'):
            log_data["correlation_id"] = record.correlation_id

        log_data["environment"] = getattr(settings, 'ENVIRONMENT', 'unknown')
        log_data["service"] = getattr(settings, 'APP_NAME', 'api')

        if record.exc_info:
            log_data["exception"] = {
                "type": record.exc_info[0].__name__ if record.exc_info[0] else None,
                "message": str(record.exc_info[1]) if record.exc_info[1] else None,
                "traceback": self.formatException(record.exc_info) if record.exc_info else None
            }

        if hasattr(record, '__dict__'):
            for key, value in record.__dict__.items():
                if key not in [
                    'name', 'msg', 'args', 'created', 'filename', 'funcName',
                    'levelname', 'levelno', 'lineno', 'module', 'msecs',
                    'message', 'pathname', 'process', 'processName', 'relativeCreated',
                    'thread', 'threadName', 'exc_info', 'exc_text', 'stack_info',
                    'request_id', 'user_id', 'correlation_id'
                ]:
                    if not key.startswith('_'):
                        try:
                            json.dumps(value)  # Check if serializable
                            log_data[key] = value
                        except (TypeError, ValueError):
                            log_data[key] = str(value)

        return json.dumps(log_data, default=str)


def setup_structured_logging():
    log_level = getattr(settings, 'LOG_LEVEL', 'INFO')
    log_level_value = getattr(logging, log_level.upper(), logging.INFO)

    log_directory = Path(getattr(settings, 'LOG_DIR', './logs'))
    log_directory.mkdir(parents=True, exist_ok=True)

    root_logger = logging.getLogger()
    root_logger.setLevel(log_level_value)
    root_logger.handlers.clear()

    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(log_level_value)
    console_handler.setFormatter(JsonFormatter())
    root_logger.addHandler(console_handler)

    file_handler = logging.FileHandler(
        filename=log_directory / "ycpa.json.log",
        encoding='utf-8'
    )
    file_handler.setLevel(log_level_value)
    file_handler.setFormatter(JsonFormatter())
    root_logger.addHandler(file_handler)

    error_handler = logging.FileHandler(
        filename=log_directory / "error.json.log",
        encoding='utf-8'
    )
    error_handler.setLevel(logging.ERROR)
    error_handler.setFormatter(JsonFormatter())
    root_logger.addHandler(error_handler)

    logging.getLogger("urllib3").setLevel(logging.WARNING)
    logging.getLogger("boto3").setLevel(logging.WARNING)
    logging.getLogger("botocore").setLevel(logging.WARNING)

    root_logger.info(
        "Structured JSON logging configured",
        extra={
            "log_level": log_level,
            "log_directory": str(log_directory)
        }
    )

