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
import time
from typing import Callable, Dict, Optional, Set

try:
    import psutil

    PSUTIL_AVAILABLE = True
except ImportError:  # pragma: no cover - tritt nur ausserhalb von Windows auf
    PSUTIL_AVAILABLE = False

logger = logging.getLogger("AutoCloseV8.Opener")


class ProgramOpener:
    """Hintergrund-Automatik, die Programme aus der OPEN-Liste startet/offen haelt."""

    # Sicherheitsbremse: dasselbe Programm wird fruehestens nach dieser Zeit
    # erneut gestartet - verhindert Endlos-Neustarts, falls ein Programm nicht
    # zuverlaessig als "laufend" erkannt werden kann.
    LAUNCH_COOLDOWN_SECONDS = 30.0
    # Nach so vielen Starts ohne dass das Programm je als laufend gesehen
    # wurde, wird der automatische Neustart fuer dieses Programm pausiert.
    MAX_UNSEEN_LAUNCHES = 2

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
        self._target_cache: Dict[str, Optional[str]] = {}
        self._last_launch: Dict[str, float] = {}
        self._unseen_launches: Dict[str, int] = {}
        self._paused_warned: Set[str] = set()

    @property
    def is_running(self) -> bool:
        """True, solange die OPEN-Automatik aktiv ist."""
        return self._running

    def start(self) -> None:
        """Startet die OPEN-Automatik in einem Hintergrund-Thread."""
        if self._running:
            return
        # Frischer Start: Zaehler und Warnungen zuruecksetzen.
        self._unseen_launches.clear()
        self._paused_warned.clear()
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

    def _resolve_lnk_target(self, program: str) -> Optional[str]:
        """
        Loest bei .lnk-Verknuepfungen den Namen der Ziel-Programmdatei auf
        (z. B. 'Google Chrome.lnk' -> 'chrome.exe'). Ergebnis wird gecacht.
        """
        if not program.lower().endswith(".lnk") or sys.platform != "win32":
            return None
        if program in self._target_cache:
            return self._target_cache[program]
        target: Optional[str] = None
        try:
            import pythoncom  # type: ignore
            import win32com.client  # type: ignore

            pythoncom.CoInitialize()
            try:
                shell = win32com.client.Dispatch("WScript.Shell")
                shortcut = shell.CreateShortCut(program)
                target_path = shortcut.Targetpath
                if target_path:
                    target = os.path.basename(target_path).lower()
            finally:
                pythoncom.CoUninitialize()
        except Exception as exc:
            logger.debug("Verknuepfungs-Ziel von '%s' nicht aufloesbar: %s", program, exc)
        self._target_cache[program] = target
        return target

    def _is_probably_running(self, program: str, running_names: Set[str]) -> bool:
        """Prueft, ob das Programm (oder das Ziel seiner Verknuepfung) laeuft."""
        base = os.path.basename(program).lower()
        stem = os.path.splitext(base)[0]
        candidates = {base, f"{stem}.exe"}
        target = self._resolve_lnk_target(program)
        if target:
            candidates.add(target)
            candidates.add(f"{os.path.splitext(target)[0]}.exe")
        return any(name in running_names for name in candidates)

    def _scan_and_open(self) -> int:
        """Startet alle Programme der OPEN-Liste, die derzeit nicht laufen."""
        programs = self._config.open_programs
        if not programs:
            return 0

        running_names: Set[str] = set()
        if PSUTIL_AVAILABLE:
            for proc in psutil.process_iter(["name"]):
                try:
                    running_names.add((proc.info.get("name") or "").lower())
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    continue

        now = time.monotonic()
        started = 0
        for program in programs:
            if self._is_probably_running(program, running_names):
                # Programm laeuft - Zaehler zuruecksetzen.
                self._unseen_launches[program] = 0
                self._paused_warned.discard(program)
                continue

            # Sicherheitsbremse 1: Abkuehlzeit zwischen zwei Starts.
            last = self._last_launch.get(program)
            if last is not None and (now - last) < self.LAUNCH_COOLDOWN_SECONDS:
                continue

            # Sicherheitsbremse 2: Wenn das Programm nach mehreren Starts nie
            # als laufend erkannt wurde, nicht endlos weiter starten.
            if self._unseen_launches.get(program, 0) >= self.MAX_UNSEEN_LAUNCHES:
                if program not in self._paused_warned:
                    self._paused_warned.add(program)
                    base = os.path.basename(program)
                    message = (
                        f"'{base}' wird nach dem Start nicht als laufend erkannt - "
                        "automatischer Neustart fuer dieses Programm pausiert."
                    )
                    logger.warning(message)
                    if self._on_error:
                        self._on_error(message)
                continue

            try:
                if sys.platform == "win32":
                    os.startfile(program)  # noqa: S606 - bewusster Programmstart
                else:
                    subprocess.Popen([program])
                self._last_launch[program] = now
                self._unseen_launches[program] = self._unseen_launches.get(program, 0) + 1
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
