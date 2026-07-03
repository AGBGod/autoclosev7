"""
window_monitor.py
-------------------
Kernlogik zur Erkennung und zum Schliessen von Fenstern/Prozessen.

Dieses Modul verwendet die Windows-API (pywin32) und funktioniert daher nur unter
Windows. Die Ueberwachung laeuft in einem eigenen Hintergrund-Thread mit
einstellbarem Intervall, um die CPU-Last minimal zu halten (kein "busy waiting").
"""

import logging
import threading
from typing import Callable, Optional

try:
    import psutil
    import win32con
    import win32gui
    import win32process

    PLATFORM_SUPPORTED = True
except ImportError:  # pragma: no cover - tritt nur ausserhalb von Windows auf
    PLATFORM_SUPPORTED = False

from .config_manager import ConfigManager
from .stats import StatsTracker

logger = logging.getLogger("AutoCloseV7.Monitor")


class WindowMonitor:
    """
    Ueberwacht periodisch alle offenen Fenster und Prozesse und schliesst jene,
    die auf der Zielliste stehen.

    Die Erkennung erfolgt ueber:
      - Fenstertitel (Teilstring-Vergleich, Gross-/Kleinschreibung wird ignoriert)
      - Prozessnamen (exakter Vergleich, z. B. "notepad.exe")
    """

    def __init__(
        self,
        config: ConfigManager,
        stats: StatsTracker,
        on_item_closed: Optional[Callable[[str, str], None]] = None,
        on_error: Optional[Callable[[str], None]] = None,
    ):
        self._config = config
        self._stats = stats
        self._on_item_closed = on_item_closed
        self._on_error = on_error

        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._running = False

        if not PLATFORM_SUPPORTED:
            logger.warning(
                "pywin32/psutil nicht verfuegbar - die Ueberwachung kann auf diesem "
                "System nicht ausgefuehrt werden. AutoCloseV7 ist fuer Windows konzipiert."
            )

    @property
    def is_running(self) -> bool:
        """Gibt zurueck, ob die Ueberwachung aktuell aktiv ist."""
        return self._running

    def start(self) -> None:
        """Startet den Ueberwachungs-Thread, falls er nicht bereits laeuft."""
        if self._running:
            logger.debug("Ueberwachung laeuft bereits - Start-Anfrage ignoriert.")
            return

        if not PLATFORM_SUPPORTED:
            message = "Diese Funktion benoetigt Windows (pywin32/psutil fehlen)."
            logger.error(message)
            if self._on_error:
                self._on_error(message)
            return

        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._run_loop, name="WindowMonitorThread", daemon=True
        )
        self._thread.start()
        self._running = True
        logger.info("Ueberwachung gestartet.")

    def stop(self) -> None:
        """Stoppt den Ueberwachungs-Thread sauber."""
        if not self._running:
            return
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=5)
        self._running = False
        logger.info("Ueberwachung gestoppt.")

    def toggle(self) -> None:
        """Wechselt zwischen Start und Stop (z. B. fuer den Hotkey)."""
        if self._running:
            self.stop()
        else:
            self.start()

    def _run_loop(self) -> None:
        """Haupt-Schleife des Hintergrund-Threads - laeuft bis stop() aufgerufen wird."""
        while not self._stop_event.is_set():
            interval = 2.0  # Sicherer Standardwert, falls die Konfiguration defekt ist.
            try:
                interval = float(self._config.get("check_interval_seconds", 2.0))
                if interval <= 0:
                    raise ValueError(f"Intervall muss positiv sein, ist aber {interval}")
            except (TypeError, ValueError) as exc:
                interval = 2.0
                message = f"Ungueltiges Pruefintervall in der Konfiguration ({exc}) - nutze 2.0 Sekunden."
                logger.error(message)
                if self._on_error:
                    self._on_error(message)
            try:
                self._scan_and_close()
            except Exception as exc:  # Absichtlich breit gefangen, damit der Thread nie abstuerzt.
                message = f"Unerwarteter Fehler bei der Ueberwachung: {exc}"
                logger.exception(message)
                if self._on_error:
                    self._on_error(message)
            # Intervall einhalten, aber schnell auf stop() reagieren koennen.
            self._stop_event.wait(timeout=max(0.2, interval))

    def _scan_and_close(self) -> None:
        """Ein einzelner Durchlauf: alle Fenster pruefen und Treffer schliessen."""
        window_titles = [t.lower() for t in self._config.window_titles]
        process_names = [p.lower() for p in self._config.process_names]

        if not window_titles and not process_names:
            return  # Nichts zu tun - spart CPU-Zyklen.

        matches = []

        def enum_handler(hwnd, _extra):
            if not win32gui.IsWindowVisible(hwnd):
                return
            title = win32gui.GetWindowText(hwnd)
            if not title:
                return

            title_match = any(needle in title.lower() for needle in window_titles)
            process_match = False
            process_label = None

            if process_names:
                try:
                    _, pid = win32process.GetWindowThreadProcessId(hwnd)
                    proc = psutil.Process(pid)
                    proc_name = proc.name().lower()
                    if proc_name in process_names:
                        process_match = True
                        process_label = proc_name
                except Exception:
                    # Prozess evtl. bereits beendet oder kein Zugriff moeglich - ignorieren.
                    pass

            if title_match or process_match:
                matches.append((hwnd, title, process_label))

        win32gui.EnumWindows(enum_handler, None)

        for hwnd, title, process_label in matches:
            self._close_window(hwnd, title, process_label)

    def _close_window(self, hwnd: int, title: str, process_label: Optional[str]) -> None:
        """Schliesst ein einzelnes Fenster - zuerst sanft (WM_CLOSE), sonst ueber den Prozess."""
        close_method = self._config.get("close_method", "graceful")
        label = process_label or title or f"Fenster #{hwnd}"

        try:
            if close_method == "graceful":
                win32gui.PostMessage(hwnd, win32con.WM_CLOSE, 0, 0)
            else:
                _, pid = win32process.GetWindowThreadProcessId(hwnd)
                psutil.Process(pid).terminate()

            logger.info("Geschlossen: %s", label)
            self._stats.record_closed(label, kind="process" if process_label else "window")
            if self._on_item_closed:
                self._on_item_closed(label, "process" if process_label else "window")

        except Exception as exc:
            message = f"Konnte '{label}' nicht schliessen: {exc}"
            logger.error(message)
            if self._on_error:
                self._on_error(message)
