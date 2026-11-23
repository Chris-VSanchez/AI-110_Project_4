"""Central logging setup shared by the game UI, the AI hint module and the evaluator."""

import logging
import os
from logging.handlers import RotatingFileHandler

LOG_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "logs")
LOG_FILE = os.path.join(LOG_DIR, "game.log")
_FORMAT = "%(asctime)s | %(levelname)-7s | %(name)s | %(message)s"

def get_logger(name: str) -> logging.Logger:
    """Return a logger that writes to logs/game.log (and the console for warnings+).

    Safe to call many times: handlers are attached to the shared "glitch" parent
    logger only once, so Streamlit reruns don't duplicate log lines.
    """

    parent = logging.getLogger("glitch")

    if not parent.handlers:
        parent.setLevel(logging.INFO)
        parent.propagate = False

        try:
            os.makedirs(LOG_DIR, exist_ok=True)
            file_handler = RotatingFileHandler(
                LOG_FILE, maxBytes=1_000_000, backupCount=3, encoding="utf-8"
            )
            file_handler.setFormatter(logging.Formatter(_FORMAT))
            file_handler.setLevel(logging.INFO)
            parent.addHandler(file_handler)
        except OSError:
            # If the log folder can't be written, keep running with console logging only.
            pass

        console = logging.StreamHandler()
        console.setFormatter(logging.Formatter(_FORMAT))
        console.setLevel(logging.WARNING)
        parent.addHandler(console)

    return parent.getChild(name)