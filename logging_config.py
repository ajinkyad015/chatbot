import json
import logging
import os
from logging.handlers import RotatingFileHandler


LOG_DIR = "logs"
LOG_FILE = os.path.join(LOG_DIR, "app.log")

os.makedirs(LOG_DIR, exist_ok=True)


class JSONFormatter(logging.Formatter):
    def format(self, record):
        log_record = {
            "timestamp": self.formatTime(
                record,
                "%Y-%m-%dT%H:%M:%S",
            ),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }

        if hasattr(record, "event_data"):
            log_record.update(record.event_data)

        if record.exc_info:
            log_record["exception"] = self.formatException(
                record.exc_info
            )

        return json.dumps(log_record)


handler = RotatingFileHandler(
    LOG_FILE,
    maxBytes=5 * 1024 * 1024,  # 5 MB
    backupCount=3,
    encoding="utf-8",
)

handler.setFormatter(JSONFormatter())

logger = logging.getLogger("app")
logger.setLevel(logging.INFO)
logger.addHandler(handler)

# Prevent duplicate output through the root logger.
logger.propagate = False