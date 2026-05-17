import logging
from pathlib import Path


SCRIPT_DIR = Path(__file__).resolve().parent
LOG_FILE = SCRIPT_DIR / "ру_log.log"

LEVEL_COLORS = {
    logging.DEBUG: "\033[36m",
    logging.INFO: "\033[32m",
    logging.WARNING: "\033[33m",
    logging.ERROR: "\033[31m",
    logging.CRITICAL: "\033[35m",
}
RESET_COLOR = "\033[0m"


class ColorFileFormatter(logging.Formatter):
    default_time_format = "%Y-%m-%d %H:%M:%S"

    def format(self, record: logging.LogRecord) -> str:
        color = LEVEL_COLORS.get(record.levelno, "")
        original_levelname = record.levelname
        original_message = record.msg
        original_args = record.args

        if color:
            record.levelname = f"{color}{record.levelname}{RESET_COLOR}"
            record.msg = f"{color}{record.getMessage()}{RESET_COLOR}"
            record.args = ()

        try:
            return super().format(record)
        finally:
            record.levelname = original_levelname
            record.msg = original_message
            record.args = original_args


def setup_stage_logger(name: str) -> logging.Logger:
    logger = logging.getLogger(name)
    if getattr(logger, "_ru_log_configured", False):
        return logger

    logger.setLevel(logging.DEBUG)
    logger.propagate = False

    handler = logging.FileHandler(LOG_FILE, encoding="utf-8")
    handler.setLevel(logging.DEBUG)
    handler.setFormatter(
        ColorFileFormatter("%(asctime)s | %(levelname)s | %(message)s")
    )
    logger.addHandler(handler)

    logger._ru_log_configured = True
    return logger


def emit_level_probe(logger: logging.Logger, stage_label: str) -> None:
    if getattr(logger, "_ru_probe_emitted", False):
        return

    logger.debug("%s: тест уровня DEBUG.", stage_label)
    logger.info("%s: тест уровня INFO.", stage_label)
    logger.warning("%s: тест уровня WARNING.", stage_label)
    logger.error("%s: тест уровня ERROR.", stage_label)
    logger.critical("%s: тест уровня CRITICAL.", stage_label)

    logger._ru_probe_emitted = True
