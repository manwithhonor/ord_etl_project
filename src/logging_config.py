import logging
import queue
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path


class GuiQueueHandler(logging.Handler):
    def __init__(self, log_queue: queue.Queue):
        super().__init__()
        self.log_queue = log_queue

    def emit(self, record: logging.LogRecord):
        try:
            message = record.getMessage()

            if record.levelno >= logging.ERROR:
                message = f"ОШИБКА: {message}"
            elif record.levelno >= logging.WARNING:
                message = f"ВНИМАНИЕ: {message}"

            self.log_queue.put(message)

        except Exception:
            self.handleError(record)


def setup_logging(
    log_dir: Path,
    gui_queue: queue.Queue | None = None,
    console: bool = False,
) -> Path:

    log_dir.mkdir(
        parents=True,
        exist_ok=True
    )

    log_path = log_dir / "app.log"

    root_logger = logging.getLogger()
    root_logger.setLevel(logging.INFO)

    # Чтобы при повторном вызове setup_logging
    # сообщения не дублировались.
    root_logger.handlers.clear()

    # -------------------------
    # Логирование в файл
    # -------------------------

    file_handler = RotatingFileHandler(
        log_path,
        maxBytes=2_000_000,
        backupCount=5,
        encoding="utf-8",
    )

    file_handler.setLevel(logging.INFO)

    file_handler.setFormatter(
        logging.Formatter(
            "%(asctime)s | %(levelname)s | "
            "%(name)s | %(message)s"
        )
    )

    root_logger.addHandler(
        file_handler
    )

    # -------------------------
    # Логирование в терминал
    # -------------------------

    if console:
        console_handler = logging.StreamHandler(
            sys.stdout
        )

        console_handler.setLevel(
            logging.INFO
        )

        console_handler.setFormatter(
            logging.Formatter(
                "%(levelname)s: %(message)s"
            )
        )

        root_logger.addHandler(
            console_handler
        )

    # -------------------------
    # Логирование в GUI
    # -------------------------

    if gui_queue is not None:
        gui_handler = GuiQueueHandler(
            gui_queue
        )

        gui_handler.setLevel(
            logging.INFO
        )

        root_logger.addHandler(
            gui_handler
        )

    return log_path