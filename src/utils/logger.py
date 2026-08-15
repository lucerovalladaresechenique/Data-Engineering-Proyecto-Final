"""
logger.py — Logger estándar del pipeline.
Mismo patrón que el ejemplo del profesor (src.utils.logger.get_logger).
"""
import logging
import sys


def get_logger(name: str, level: int = logging.INFO) -> logging.Logger:
    logger = logging.getLogger(name)
    if not logger.handlers:
        handler = logging.StreamHandler(sys.stdout)
        handler.setFormatter(logging.Formatter(
            "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"
        ))
        logger.addHandler(handler)
        logger.setLevel(level)
    return logger
