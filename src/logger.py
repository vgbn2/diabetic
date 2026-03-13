import logging
import sys
from pathlib import Path

def setup_logger(name: str = "BioQuant", log_file: str = "app.log"):
    """
    Sets up a structured logger to both console and file.
    Ensures that logs are saved to the project's logs directory.
    """
    # Create logs directory if it doesn't exist
    log_dir = Path(__file__).parent.parent / "logs"
    log_dir.mkdir(exist_ok=True)
    
    logger = logging.getLogger(name)
    logger.setLevel(logging.INFO)

    # Format for logs
    formatter = logging.Formatter(
        '%(asctime)s | %(levelname)-8s | %(name)s | %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )

    # Console Handler
    stdout_handler = logging.StreamHandler(sys.stdout)
    stdout_handler.setFormatter(formatter)
    logger.addHandler(stdout_handler)

    # File Handler
    file_handler = logging.FileHandler(log_dir / log_file)
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)

    return logger

# Shared logger instance
logger = setup_logger()
