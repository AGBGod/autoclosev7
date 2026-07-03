"""
program_opener.py
------------------
Automatik fuer die OPEN-Liste: startet die eingetragenen Programme und haelt
sie am Laufen. In jedem Pruef-Durchlauf wird geschaut, ob die Programme bereits
laufen - fehlende Programme werden (erneut) gestartet.

Das Pruef-Intervall kommt aus der Konfiguration (Sektion 'open_auto') und kann
in der GUI mit Einheit (ms/s/m/h) eingestellt werden.
"""

import logging
import os
import subprocess
import sys
import threading
from typing import Callable, Optional

try:
    import psutil

    PSUTIL_AVAILABLE = True
except ImportError:  # pragma: no cover - tritt nur ausserhalb von Windows auf
    PSUTIL_AVAILABLE = False

logger = logging.getLogger("AutoCloseV7.Opener")


class ProgramOpener:
    """Hintergrund-Automatik, die Programme aus der OPEN-Liste startet/offen haelt."""

    def __init__(
        self,
        config,
        on_opened: Optional[Callable[[str], None]] = None,
        on_error: Optional[Callable[[str], None]] = None,
    ):
        self._config = config
        self._on_opened = on_opened
        self._on_error = on_error
        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._running = False

    @property
    def is_running(self) -> bool:
        """True, solange die OPEN-Automatik aktiv ist."""
        return self._running

    def start(self) -> None:
        """Startet die OPEN-Automatik in einem Hintergrund-Thread."""
        if self._running:
            return
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._run_loop, name="ProgramOpener", daemon=True
        )
        self._running = True
        self._thread.start()
        logger.info("OPEN-Automatik gestartet.")

    def stop(self) -> None:
        """Stoppt die OPEN-Automatik."""
        if not self._running:
            return
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=5)
        self._running = False
        logger.info("OPEN-Automatik gestoppt.")

    def toggle(self) -> None:
        """Wechselt zwischen Start und Stop."""
        if self._running:
            self.stop()
        else:
            self.start()

    def open_missing_once(self) -> int:
        """Ein einzelner Durchlauf: startet alle Programme, die noch nicht laufen."""
        try:
            return self._scan_and_open()
        except Exception as exc:
            message = f"Unerwarteter Fehler beim Starten: {exc}"
            logger.exception(message)
            if self._on_error:
                self._on_error(message)
            return 0

    def _interval_seconds(self) -> float:
        """Liest das Pruef-Intervall (Sekunden) aus der Konfiguration."""
        section = self._config.get_auto_section("open_auto")
        try:
            interval = float(section.get("interval_seconds", 2.0))
        except (TypeError, ValueError):
            interval = 2.0
        return max(0.2, interval)

    def _run_loop(self) -> None:
        """Haupt-Schleife des Hintergrund-Threads - laeuft bis stop()."""
        while not self._stop_event.is_set():
            try:
                self._scan_and_open()
            except Exception as exc:
                message = f"Fehler in der OPEN-Automatik: {exc}"
                logger.exception(message)
                if self._on_error:
                    self._on_error(message)
            self._stop_event.wait(timeout=self._interval_seconds())

    def _scan_and_open(self) -> int:
        """Startet alle Programme der OPEN-Liste, die derzeit nicht laufen."""
        programs = self._config.open_programs
        if not programs:
            return 0

        running_names = set()
        if PSUTIL_AVAILABLE:
            for proc in psutil.process_iter(["name"]):
                try:
                    running_names.add((proc.info.get("name") or "").lower())
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    continue

        started = 0
        for program in programs:
            base = os.path.basename(program).lower()
            stem = os.path.splitext(base)[0]
            # Laeuft das Programm schon? (auch Verknuepfungen wie foo.lnk -> foo.exe)
            if base in running_names or f"{stem}.exe" in running_names:
                continue
            try:
                if sys.platform == "win32":
                    os.startfile(program)  # noqa: S606 - bewusster Programmstart
                else:
                    subprocess.Popen([program])
                started += 1
                logger.info("Automatisch gestartet: %s", program)
                if self._on_opened:
                    self._on_opened(program)
            except Exception as exc:
                message = f"Konnte '{program}' nicht starten: {exc}"
                logger.error(message)
                if self._on_error:
                    self._on_error(message)
        return started
