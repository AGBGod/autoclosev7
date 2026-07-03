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
import os
import sys
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


# Woerter, die auf Deinstallations-/Hilfe-Verknuepfungen hindeuten - solche
# Eintraege sind fuer den Nutzer beim Hinzufuegen von Apps nicht interessant.
_SKIP_WORDS = ("uninstall", "deinstall", "entfernen", "readme", "hilfe", "help",
               "website", "homepage", "dokumentation", "documentation")


def list_installed_apps() -> List[Tuple[str, str]]:
    """
    Liefert die installierten "normalen" Apps als Liste von
    (Anzeigename, Pfad zur .lnk-Verknuepfung) - alphabetisch sortiert.

    Quelle sind die Startmenue-Ordner von Windows (Benutzer + alle Benutzer).
    Dort legt praktisch jedes installierte Programm eine Verknuepfung ab.
    """
    apps = {}
    if sys.platform != "win32":
        return []

    start_menu_dirs = []
    appdata = os.environ.get("APPDATA")
    if appdata:
        start_menu_dirs.append(
            os.path.join(appdata, "Microsoft", "Windows", "Start Menu", "Programs")
        )
    programdata = os.environ.get("PROGRAMDATA")
    if programdata:
        start_menu_dirs.append(
            os.path.join(programdata, "Microsoft", "Windows", "Start Menu", "Programs")
        )

    for base_dir in start_menu_dirs:
        if not os.path.isdir(base_dir):
            continue
        try:
            for root, _dirs, files in os.walk(base_dir):
                for filename in files:
                    if not filename.lower().endswith(".lnk"):
                        continue
                    name = filename[:-4]
                    lower = name.lower()
                    if any(word in lower for word in _SKIP_WORDS):
                        continue
                    if lower not in apps:
                        apps[lower] = (name, os.path.join(root, filename))
        except OSError as exc:
            logger.error("Startmenue-Ordner nicht lesbar (%s): %s", base_dir, exc)

    return sorted(apps.values(), key=lambda item: item[0].lower())


def resolve_shortcut_target(lnk_path: str) -> str:
    """
    Loest eine .lnk-Verknuepfung auf und liefert den Dateinamen der
    Ziel-Programmdatei (z. B. 'chrome.exe'). Bei Problemen: leerer String.
    """
    if sys.platform != "win32":
        return ""
    try:
        import pythoncom  # type: ignore
        import win32com.client  # type: ignore

        pythoncom.CoInitialize()
        try:
            shell = win32com.client.Dispatch("WScript.Shell")
            shortcut = shell.CreateShortCut(lnk_path)
            target = (shortcut.Targetpath or "").strip()
            if target.lower().endswith(".exe"):
                return os.path.basename(target)
            return ""
        finally:
            pythoncom.CoUninitialize()
    except Exception as exc:
        logger.debug("Verknuepfung nicht aufloesbar (%s): %s", lnk_path, exc)
        return ""
