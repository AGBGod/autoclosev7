"""
process_list.py
----------------
Hilfsfunktionen, um - aehnlich wie im Task-Manager - die gerade offenen
Fenster und laufenden Programme aufzulisten. Wird von den Auswahl-Dialogen
der GUI benutzt (+ Knopf bei OPEN und CLOSE).

Funktioniert nur unter Windows vollstaendig; auf anderen Systemen werden
leere Listen zurueckgegeben.
"""

import logging
from typing import List, Tuple

try:
    import psutil

    PSUTIL_AVAILABLE = True
except ImportError:  # pragma: no cover - tritt nur ausserhalb von Windows auf
    PSUTIL_AVAILABLE = False

try:
    import win32gui

    WIN32_AVAILABLE = True
except ImportError:  # pragma: no cover
    WIN32_AVAILABLE = False

logger = logging.getLogger("AutoCloseV8.ProcessList")


def list_open_windows() -> List[str]:
    """Liefert die Titel aller sichtbaren Fenster (alphabetisch sortiert)."""
    titles: List[str] = []
    if not WIN32_AVAILABLE:
        return titles

    def handler(hwnd, _extra):
        try:
            if not win32gui.IsWindowVisible(hwnd):
                return
            title = win32gui.GetWindowText(hwnd)
            if title and title not in titles:
                titles.append(title)
        except Exception:
            # Einzelne Fenster koennen waehrend der Aufzaehlung verschwinden.
            pass

    try:
        win32gui.EnumWindows(handler, None)
    except Exception as exc:
        logger.error("Fenster konnten nicht aufgelistet werden: %s", exc)
    return sorted(titles, key=str.lower)


def list_running_programs() -> List[Tuple[str, str]]:
    """
    Liefert die laufenden Programme als Liste von (Prozessname, Pfad zur Datei).
    Jeder Prozessname erscheint nur einmal (alphabetisch sortiert).
    """
    seen = {}
    if not PSUTIL_AVAILABLE:
        return []
    try:
        for proc in psutil.process_iter(["name", "exe"]):
            try:
                name = (proc.info.get("name") or "").strip()
                if not name:
                    continue
                key = name.lower()
                if key not in seen:
                    seen[key] = (name, proc.info.get("exe") or "")
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
    except Exception as exc:
        logger.error("Prozesse konnten nicht aufgelistet werden: %s", exc)
    return sorted(seen.values(), key=lambda item: item[0].lower())
