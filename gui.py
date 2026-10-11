from __future__ import annotations

import logging
import queue
import sys
import threading
from datetime import date
from pathlib import Path

import tkinter as tk
from tkinter import ttk, messagebox

import yaml
from dotenv import load_dotenv

from src.handler_factory import HandlerFactory
from src.logging_config import setup_logging


logger = logging.getLogger(__name__)


def get_app_dir() -> Path:
    """
    При обычном запуске возвращает папку проекта.
    При запуске EXE — папку, в которой лежит EXE.
    """

    if getattr(sys, "frozen", False):
        return Path(
            sys.executable
        ).resolve().parent

    return Path(
        __file__
    ).resolve().parent


APP_DIR = get_app_dir()


def load_config(path: Path) -> dict:
    with open(
        path,
        "r",
        encoding="utf-8"
    ) as fh:
        return yaml.safe_load(fh)


class OrdApp:

    def __init__(
        self,
        root: tk.Tk
    ):
        self.root = root

        self.root.title(
            "Отчётность ОРД"
        )

        self.root.geometry(
            "600x470"
        )

        self.root.resizable(
            False,
            False
        )

        # Очередь между logging
        # и главным потоком Tkinter.
        self.log_queue = queue.Queue()

        self.log_path = setup_logging(
            APP_DIR / "logs",
            gui_queue=self.log_queue,
        )

        self.report_date_var = (
            tk.StringVar(
                value=self._get_default_report_date()
            )
        )

        self.status_var = (
            tk.StringVar(
                value="Готов к запуску"
            )
        )

        self._build_ui()

        # Каждые 100 мс проверяем,
        # появились ли новые логи.
        self.root.after(
            100,
            self._process_log_queue
        )

        logger.info(
            "Программа запущена"
        )

    def _get_default_report_date(
        self
    ) -> str:

        try:
            config = load_config(
                APP_DIR / "config.yaml"
            )

            return str(
                config["app"]["report_date"]
            )

        except Exception:
            return date.today().isoformat()

    def _build_ui(self):

        main_frame = ttk.Frame(
            self.root,
            padding=20
        )

        main_frame.pack(
            fill="both",
            expand=True
        )

        title = ttk.Label(
            main_frame,
            text="Передача статистики в ОРД",
            font=(
                "Segoe UI",
                15,
                "bold"
            )
        )

        title.pack(
            pady=(0, 20)
        )

        date_frame = ttk.Frame(
            main_frame
        )

        date_frame.pack(
            fill="x"
        )

        ttk.Label(
            date_frame,
            text="Дата отчёта:"
        ).pack(
            side="left"
        )

        self.date_entry = ttk.Entry(
            date_frame,
            textvariable=
                self.report_date_var,
            width=18
        )

        self.date_entry.pack(
            side="right"
        )

        ttk.Label(
            main_frame,
            text="Формат: ГГГГ-ММ-ДД",
            foreground="gray"
        ).pack(
            anchor="e",
            pady=(3, 15)
        )

        self.run_button = ttk.Button(
            main_frame,
            text="Запустить отчёт",
            command=self.start_run
        )

        self.run_button.pack(
            ipadx=30,
            ipady=8,
            pady=(0, 15)
        )

        ttk.Separator(
            main_frame
        ).pack(
            fill="x",
            pady=(5, 15)
        )

        ttk.Label(
            main_frame,
            text="Ход выполнения:",
            font=(
                "Segoe UI",
                10,
                "bold"
            )
        ).pack(
            anchor="w"
        )

        # Поле с логами.
        log_frame = ttk.Frame(
            main_frame
        )

        log_frame.pack(
            fill="both",
            expand=True,
            pady=(5, 10)
        )

        scrollbar = ttk.Scrollbar(
            log_frame
        )

        scrollbar.pack(
            side="right",
            fill="y"
        )

        self.log_text = tk.Text(
            log_frame,
            height=12,
            wrap="word",
            state="disabled",
            yscrollcommand=
                scrollbar.set,
            font=(
                "Consolas",
                9
            )
        )

        self.log_text.pack(
            side="left",
            fill="both",
            expand=True
        )

        scrollbar.config(
            command=
                self.log_text.yview
        )

        ttk.Separator(
            main_frame
        ).pack(
            fill="x"
        )

        self.status_label = ttk.Label(
            main_frame,
            textvariable=
                self.status_var
        )

        self.status_label.pack(
            anchor="w",
            pady=(10, 0)
        )

    def _append_log(
        self,
        message: str
    ):

        self.log_text.config(
            state="normal"
        )

        self.log_text.insert(
            "end",
            message + "\n"
        )

        self.log_text.see(
            "end"
        )

        self.log_text.config(
            state="disabled"
        )

    def _process_log_queue(self):
        """
        Выполняется только
        в главном Tkinter-потоке.
        """

        try:
            while True:
                message = (
                    self.log_queue
                    .get_nowait()
                )

                self._append_log(
                    message
                )

        except queue.Empty:
            pass

        self.root.after(
            100,
            self._process_log_queue
        )

    def validate_report_date(
        self
    ) -> str:

        value = (
            self.report_date_var
            .get()
            .strip()
        )

        try:
            parsed = (
                date.fromisoformat(
                    value
                )
            )

        except ValueError:
            raise ValueError(
                "Дата должна быть "
                "в формате ГГГГ-ММ-ДД.\n"
                "Например: 2026-09-30"
            )

        return parsed.isoformat()

    def start_run(self):

        try:
            report_date = (
                self.validate_report_date()
            )

        except ValueError as exc:
            messagebox.showerror(
                "Ошибка",
                str(exc)
            )
            return

        self.run_button.config(
            state="disabled"
        )

        self.date_entry.config(
            state="disabled"
        )

        self.status_var.set(
            "Выполняется..."
        )

        # Очищаем окно логов
        # перед новым запуском.
        self.log_text.config(
            state="normal"
        )

        self.log_text.delete(
            "1.0",
            "end"
        )

        self.log_text.config(
            state="disabled"
        )

        thread = threading.Thread(
            target=self.run_etl,
            args=(report_date,),
            daemon=True
        )

        thread.start()

    def run_etl(
        self,
        report_date: str
    ):

        try:
            logger.info(
                "Запуск отчёта за %s",
                report_date
            )

            env_path = (
                APP_DIR / ".env"
            )

            config_path = (
                APP_DIR
                / "config.yaml"
            )

            logger.info(
                "Загружаем настройки"
            )

            load_dotenv(
                env_path,
                override=True
            )

            config = load_config(
                config_path
            )

            # Единственное значение,
            # которое GUI меняет
            # в конфигурации.
            config[
                "app"
            ][
                "report_date"
            ] = report_date

            # Исправляем относительный
            # путь для credentials.
            credentials_path = Path(
                config[
                    "google"
                ][
                    "credentials_path"
                ]
            )

            if (
                not
                credentials_path
                .is_absolute()
            ):
                config[
                    "google"
                ][
                    "credentials_path"
                ] = str(
                    APP_DIR
                    / credentials_path
                )

            handler = HandlerFactory(
                config
            )

            handler.run()

        except Exception as exc:

            # traceback полностью
            # попадёт в app.log.
            logger.exception(
                "Выполнение отчёта "
                "завершилось с ошибкой"
            )

            self.root.after(
                0,
                self.on_error,
                str(exc)
            )

            return

        self.root.after(
            0,
            self.on_success
        )

    def on_success(self):

        self.status_var.set(
            "Готово"
        )

        self.run_button.config(
            state="normal"
        )

        self.date_entry.config(
            state="normal"
        )

        messagebox.showinfo(
            "Готово",
            "Отчёт успешно обработан."
        )

    def on_error(
        self,
        error_message: str
    ):

        self.status_var.set(
            "Ошибка"
        )

        self.run_button.config(
            state="normal"
        )

        self.date_entry.config(
            state="normal"
        )

        messagebox.showerror(
            "Ошибка",
            "Не удалось выполнить отчёт.\n\n"
            f"{error_message}\n\n"
            "Полная информация сохранена в:\n"
            f"{self.log_path}"
        )


def main():

    root = tk.Tk()

    OrdApp(
        root
    )

    root.mainloop()


if __name__ == "__main__":
    main()