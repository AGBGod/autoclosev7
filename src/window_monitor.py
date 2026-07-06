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

logger = logging.getLogger("AutoCloseV9.0.Monitor")


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
        on_admin_needed: Optional[Callable[[str], None]] = None,
        on_not_closed: Optional[Callable[[str], None]] = None,
        on_not_closed_summary: Optional[Callable[[list], None]] = None,
    ):
        self._config = config
        self._stats = stats
        self._on_item_closed = on_item_closed
        self._on_error = on_error
        self._on_admin_needed = on_admin_needed
        self._on_not_closed = on_not_closed
        self._on_not_closed_summary = on_not_closed_summary
        self._admin_hint_sent = False
        # Sammelt alle Programme, die im AKTUELLEN Durchlauf nicht geschlossen
        # werden konnten (z. B. wegen einer "Speichern?"-Rueckfrage). Wird zu
        # Beginn jedes Durchlaufs zurueckgesetzt und am Ende als Zusammenfassung
        # gemeldet - so sieht der Nutzer alle Ausreisser, nicht nur den letzten.
        self._not_closed_this_run: list = []

        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._running = False

        if not PLATFORM_SUPPORTED:
            logger.warning(
                "pywin32/psutil nicht verfuegbar - die Ueberwachung kann auf diesem "
                "System nicht ausgefuehrt werden. AutoCloseV9.0 ist fuer Windows konzipiert."
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

    def close_now(
        self,
        window_titles: Optional[list] = None,
        process_names: Optional[list] = None,
    ) -> int:
        """
        Fuehrt sofort einen einzelnen Schliess-Durchlauf aus (ohne die
        Dauerueberwachung zu starten). Optional koennen eigene Ziellisten
        uebergeben werden - sonst gelten die Ziele aus der Konfiguration.
        Gibt die Anzahl der geschlossenen Elemente zurueck.
        """
        if not PLATFORM_SUPPORTED:
            message = "Diese Funktion benoetigt Windows (pywin32/psutil fehlen)."
            logger.error(message)
            if self._on_error:
                self._on_error(message)
            return 0
        try:
            return self._scan_and_close(window_titles, process_names)
        except Exception as exc:
            message = f"Unerwarteter Fehler beim Schliessen: {exc}"
            logger.exception(message)
            if self._on_error:
                self._on_error(message)
            return 0

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

    def _scan_and_close(
        self,
        window_titles: Optional[list] = None,
        process_names: Optional[list] = None,
    ) -> int:
        """
        Ein einzelner Durchlauf: Ziele finden und schliessen.

        Es gibt zwei Arten von Zielen:
          - Fenstertitel: werden ueber die sichtbaren Fenster gesucht (wie im
            Task-Manager unter "Anwendungen").
          - Prozessnamen (z. B. 'chrome.exe'): werden ueber ALLE laufenden
            Prozesse gesucht - auch solche ohne sichtbares Fenster, die im
            Hintergrund oder im Infobereich (Tray) laufen.

        Gibt die Anzahl der geschlossenen Elemente zurueck.
        """
        if window_titles is None:
            window_titles = self._config.window_titles
        if process_names is None:
            process_names = self._config.process_names
        window_titles = [t.lower() for t in window_titles]
        process_names = [p.lower() for p in process_names]

        if not window_titles and not process_names:
            return 0  # Nichts zu tun - spart CPU-Zyklen.

        # Ausreisser-Liste fuer diesen Durchlauf zuruecksetzen. Alles, was jetzt
        # nicht schliesst, sammelt sich hier und wird am Ende gemeldet.
        self._not_closed_this_run = []

        # Alle sichtbaren Fenster einmalig einsammeln (hwnd, Titel, PID).
        # Diese Liste wird sowohl fuer Titel-Treffer als auch fuer ein sanftes
        # Schliessen von Prozessen mit Fenster verwendet.
        windows = []

        def enum_handler(hwnd, _extra):
            try:
                if not win32gui.IsWindowVisible(hwnd):
                    return
                title = win32gui.GetWindowText(hwnd)
                if not title:
                    return
                _, pid = win32process.GetWindowThreadProcessId(hwnd)
                windows.append((hwnd, title, pid))
            except Exception:
                # Einzelne Fenster koennen waehrend der Aufzaehlung verschwinden.
                pass

        win32gui.EnumWindows(enum_handler, None)

        handled_pids = set()
        closed = 0

        # Sanft geschlossene Ziele, deren Verschwinden noch geprueft werden muss.
        # Eintraege: (label, kind, is_gone). Die Verifikation erfolgt EINMAL fuer
        # alle Ziele gemeinsam (ueberlappend) - so summieren sich die Wartezeiten
        # bei vielen gleichzeitig "haengenden" Programmen NICHT auf.
        pending: list = []

        # 1) Fenstertitel-Treffer: jedes passende sichtbare Fenster schliessen.
        if window_titles:
            for hwnd, title, pid in windows:
                if any(needle in title.lower() for needle in window_titles):
                    result = self._close_window(hwnd, title, None)
                    if result is None:
                        continue
                    if self._handle_close_result(result, pending):
                        closed += 1
                    # Auch bei sanftem (noch ausstehendem) Schliessen die PID
                    # merken, damit der Prozess-Durchlauf dasselbe Programm nicht
                    # erneut anfasst (kein doppeltes WM_CLOSE, keine doppelte Wartezeit).
                    if pid is not None:
                        handled_pids.add(pid)

        # 2) Prozessnamen-Treffer: ueber ALLE laufenden Prozesse suchen, damit
        #    auch Programme ohne Fenster (Hintergrund/Tray) geschlossen werden.
        if process_names:
            pid_windows: dict = {}
            for hwnd, _title, pid in windows:
                if pid is not None:
                    pid_windows.setdefault(pid, []).append(hwnd)

            for proc in psutil.process_iter(["name", "pid"]):
                try:
                    name = (proc.info.get("name") or "").lower()
                    pid = proc.info.get("pid")
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    continue
                except Exception:
                    continue

                if not name or name not in process_names or pid in handled_pids:
                    continue

                result = self._close_process(proc, name, pid_windows.get(pid, []))
                if result is None:
                    continue
                if self._handle_close_result(result, pending):
                    closed += 1
                handled_pids.add(pid)

        # Alle sanft geschlossenen Ziele in EINER ueberlappenden Wartephase
        # verifizieren. Wer wirklich verschwunden ist, zaehlt als geschlossen;
        # wer noch offen ist (z. B. "Speichern?"-Rueckfrage), landet in der
        # Nicht-geschlossen-Zusammenfassung.
        closed += self._verify_pending(pending)

        # Zusammenfassung dieses Durchlaufs melden: die vollstaendige Liste aller
        # Programme, die (noch) nicht geschlossen werden konnten. Wird immer
        # gemeldet - auch leer -, damit die Anzeige beim naechsten Durchlauf
        # aktualisiert wird bzw. verschwindet.
        if self._on_not_closed_summary:
            self._on_not_closed_summary(list(self._not_closed_this_run))

        return closed

    @staticmethod
    def _is_access_denied(exc: Exception) -> bool:
        """Erkennt 'Zugriff verweigert'-Fehler (Windows-Fehlercode 5 / UIPI)."""
        if PLATFORM_SUPPORTED and isinstance(exc, psutil.AccessDenied):
            return True
        if getattr(exc, "winerror", None) == 5:
            return True
        # pywintypes.error hat den Code als erstes Argument.
        args = getattr(exc, "args", ())
        if args and args[0] == 5:
            return True
        text = str(exc).lower()
        return "zugriff verweigert" in text or "access is denied" in text

    def _report_admin_needed(self, label: str) -> None:
        """
        Meldet, dass ein Ziel (z. B. der Task-Manager) mit Administrator-
        Rechten laeuft und deshalb nicht geschlossen werden kann.
        """
        message = (
            f"'{label}' läuft mit Administrator-Rechten und kann nur geschlossen "
            "werden, wenn AutoCloseV9.0 selbst als Administrator gestartet wird."
        )
        logger.warning(message)
        if self._on_admin_needed and not self._admin_hint_sent:
            self._admin_hint_sent = True
            self._on_admin_needed(label)
        elif self._on_error:
            self._on_error(message)

    def _report_not_closed(self, label: str) -> None:
        """
        Meldet, dass ein Programm nach einem sanften Schliess-Versuch noch offen
        ist - z. B. weil eine "Speichern?"-Rueckfrage angezeigt wird. Es wird
        bewusst NICHT als geschlossen gezaehlt, damit die Statusanzeige der
        Realitaet entspricht.
        """
        message = f"'{label}' wartet auf eine Rückfrage und wurde nicht geschlossen."
        logger.info(message)
        # Fuer die Zusammenfassung am Ende des Durchlaufs merken (ohne Duplikate).
        if label not in self._not_closed_this_run:
            self._not_closed_this_run.append(label)
        if self._on_not_closed:
            self._on_not_closed(label)
        elif self._on_error:
            self._on_error(message)

    def _verify_wait_params(self) -> tuple:
        """
        Liest das Zeitbudget fuer die Schliess-Verifikation aus der Konfiguration
        (mit robusten Standardwerten). timeout = maximale Gesamtwartezeit eines
        Durchlaufs, step = Pruefschrittweite. Beides ist ueber die config.json
        einstellbar, falls die Standardwerte auf einem System zu langsam wirken.
        """
        timeout = self._read_positive_float("close_verify_timeout_seconds", 1.0)
        step = self._read_positive_float("close_verify_step_seconds", 0.1)
        # Die Schrittweite darf das Gesamtbudget nicht ueberschreiten.
        if step > timeout:
            step = timeout
        return timeout, step

    def _read_positive_float(self, key: str, default: float) -> float:
        """Liest einen positiven Float aus der Config, sonst den Standardwert."""
        try:
            value = float(self._config.get(key, default))
            if value <= 0:
                raise ValueError
            return value
        except (TypeError, ValueError):
            return default

    def _verify_pending(self, pending: list) -> int:
        """
        Wartet EINMAL - ueberlappend fuer ALLE sanft geschlossenen Ziele - darauf,
        dass sie wirklich verschwinden.

        Dadurch summieren sich die Wartezeiten NICHT auf: Auch wenn viele
        Programme gleichzeitig auf eine "Speichern?"-Rueckfrage warten, wartet der
        Durchlauf insgesamt nur bis zum gemeinsamen Zeitbudget (statt timeout pro
        Ziel). stop() bricht die Wartephase sofort ab.

        pending: Liste von (label, kind, is_gone)-Tupeln.
        Gibt die Anzahl der tatsaechlich verschwundenen (= geschlossenen) Ziele zurueck.
        """
        if not pending:
            return 0

        timeout, step = self._verify_wait_params()
        closed = 0
        remaining = timeout
        still_open = list(pending)

        while True:
            # Alle noch offenen Ziele in einem Durchgang pruefen (ueberlappend).
            survivors = []
            for label, kind, is_gone in still_open:
                if is_gone():
                    self._record_closed(label, kind)
                    closed += 1
                else:
                    survivors.append((label, kind, is_gone))
            still_open = survivors

            if not still_open or remaining <= 0:
                break

            wait_for = min(step, remaining)
            if self._stop_event.wait(timeout=wait_for):
                # stop() angefordert: letzte Momentaufnahme, dann sofort abbrechen.
                for label, kind, is_gone in still_open:
                    if is_gone():
                        self._record_closed(label, kind)
                        closed += 1
                    else:
                        self._report_not_closed(label)
                return closed
            remaining -= wait_for

        # Zeit abgelaufen: verbliebene Ziele gelten als (noch) nicht geschlossen.
        for label, _kind, _is_gone in still_open:
            self._report_not_closed(label)
        return closed

    def _record_closed(self, label: str, kind: str) -> None:
        """Verbucht ein tatsaechlich geschlossenes Ziel (Log, Statistik, Callback)."""
        logger.info("Geschlossen: %s", label)
        self._stats.record_closed(label, kind=kind)
        if self._on_item_closed:
            self._on_item_closed(label, kind)

    def _handle_close_result(self, result: tuple, pending: list) -> bool:
        """
        Verarbeitet das Ergebnis eines Schliess-Versuchs.

        - ("closed", label, kind): sofort geschlossen (erzwungen/terminate) ->
          wird sofort verbucht, gibt True zurueck (fuer die Zaehlung).
        - ("pending", label, kind, is_gone): sanft geschlossen, Verschwinden wird
          spaeter gemeinsam geprueft -> wird an 'pending' angehaengt, gibt False zurueck.
        """
        if result[0] == "closed":
            _, label, kind = result
            self._record_closed(label, kind)
            return True
        _, label, kind, is_gone = result
        pending.append((label, kind, is_gone))
        return False

    @staticmethod
    def _window_gone(hwnd: int) -> bool:
        """Prueft, ob ein Fenster nicht mehr existiert."""
        try:
            return not win32gui.IsWindow(hwnd)
        except Exception:
            # Im Zweifel gilt das Fenster als weg (es liess sich nicht mehr abfragen).
            return True

    @staticmethod
    def _process_gone(proc) -> bool:
        """Prueft, ob ein Prozess nicht mehr laeuft."""
        try:
            return not proc.is_running()
        except psutil.NoSuchProcess:
            return True
        except Exception:
            return False

    def _close_window(self, hwnd: int, title: str, process_label: Optional[str]):
        """
        Leitet das Schliessen eines einzelnen Fensters ein:
          1. Sanft per WM_CLOSE (wie ein Klick auf das X).
          2. Falls das nicht erlaubt/moeglich ist: Prozess beenden (terminate).
          3. Als letzte Stufe: Prozess erzwingen (kill).
        Laeuft das Ziel mit Administrator-Rechten, wird ein Hinweis gemeldet.

        Gibt das Ergebnis zurueck (siehe _handle_close_result):
          - ("closed", label, kind) bei erzwungenem Schliessen,
          - ("pending", label, kind, is_gone) bei sanftem Schliessen (Verschwinden
            wird spaeter gemeinsam geprueft),
          - None bei Fehler / fehlenden Rechten (bereits gemeldet).
        """
        close_method = self._config.get("close_method", "graceful")
        label = process_label or title or f"Fenster #{hwnd}"
        kind = "process" if process_label else "window"

        try:
            graceful_posted = False
            if close_method == "graceful":
                try:
                    win32gui.PostMessage(hwnd, win32con.WM_CLOSE, 0, 0)
                    graceful_posted = True
                except Exception as exc:
                    if self._is_access_denied(exc):
                        raise
                    # Sanftes Schliessen nicht moeglich -> Prozess beenden.
                    self._terminate_by_hwnd(hwnd)
            else:
                self._terminate_by_hwnd(hwnd)

            # Beim sanften Schliessen wird erst spaeter (gemeinsam) geprueft, ob
            # das Fenster wirklich verschwindet - zeigt das Programm eine
            # "Speichern?"-Rueckfrage, bleibt es offen und zaehlt nicht.
            if graceful_posted:
                return ("pending", label, kind, lambda: self._window_gone(hwnd))
            return ("closed", label, kind)

        except Exception as exc:
            if self._is_access_denied(exc):
                self._report_admin_needed(label)
                return None
            message = f"Konnte '{label}' nicht schliessen: {exc}"
            logger.error(message)
            if self._on_error:
                self._on_error(message)
            return None

    def _close_process(self, proc, label: str, hwnds: list):
        """
        Leitet das Schliessen eines kompletten Prozesses ein (anhand seines Namens
        gefunden) - auch dann, wenn er kein sichtbares Fenster hat (Hintergrund/Tray).

        Ablauf:
          1. Sanft: hat der Prozess sichtbare Fenster und ist der sanfte Modus
             aktiv, werden diese per WM_CLOSE geschlossen.
          2. Sonst / ohne Fenster: Prozess beenden (terminate), notfalls
             erzwingen (kill).
        Laeuft das Ziel mit Administrator-Rechten, wird ein Hinweis gemeldet.

        Gibt dasselbe Ergebnis-Format zurueck wie _close_window.
        """
        close_method = self._config.get("close_method", "graceful")

        try:
            graceful_posted = False
            if close_method == "graceful" and hwnds:
                posted = False
                for hwnd in hwnds:
                    try:
                        win32gui.PostMessage(hwnd, win32con.WM_CLOSE, 0, 0)
                        posted = True
                    except Exception as exc:
                        if self._is_access_denied(exc):
                            raise
                if not posted:
                    # Fenster verschwanden zwischenzeitlich -> Prozess beenden.
                    self._terminate_proc(proc)
                else:
                    graceful_posted = True
            else:
                self._terminate_proc(proc)

            # Beim sanften Schliessen wird erst spaeter (gemeinsam) geprueft, ob
            # der Prozess wirklich endet. Haengt er an einer "Speichern?"-Rueckfrage,
            # laeuft er weiter und zaehlt nicht als geschlossen.
            if graceful_posted:
                return ("pending", label, "process", lambda: self._process_gone(proc))
            return ("closed", label, "process")

        except Exception as exc:
            if self._is_access_denied(exc):
                self._report_admin_needed(label)
                return None
            message = f"Konnte '{label}' nicht schliessen: {exc}"
            logger.error(message)
            if self._on_error:
                self._on_error(message)
            return None

    def _terminate_by_hwnd(self, hwnd: int) -> None:
        """Beendet den Prozess hinter einem Fenster (terminate, notfalls kill)."""
        _, pid = win32process.GetWindowThreadProcessId(hwnd)
        self._terminate_proc(psutil.Process(pid))

    @staticmethod
    def _terminate_proc(proc) -> None:
        """Beendet einen Prozess sauber (terminate), notfalls erzwungen (kill).

        Ist der Prozess in der Zwischenzeit bereits von selbst verschwunden,
        gilt das als Erfolg (kein Fehler fuer den Nutzer).
        """
        try:
            proc.terminate()
            proc.wait(timeout=2)
        except psutil.NoSuchProcess:
            return
        except psutil.TimeoutExpired:
            try:
                proc.kill()
            except psutil.NoSuchProcess:
                return
