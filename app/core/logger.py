import logging
import logging.config
import sys


LOGGING_CONFIG = {
    "version": 1,
    "disable_existing_loggers": False,

    "formatters": {
        "standard": {
            "format": "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"
        },
        "detailed": {
            "format": "%(asctime)s | %(levelname)-8s | %(name)s:%(lineno)d | %(message)s"
        },
    },

    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
            "formatter": "standard",
            "stream": sys.stdout,
        },
    },

    "root": {
        "handlers": ["console"],
        "level": "INFO",
    },
}


def setup_logging():
    logging.config.dictConfig(LOGGING_CONFIG)


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)
