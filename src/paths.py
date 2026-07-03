"""
paths.py
---------
Zentrale Pfad-Logik fuer AutoCloseV8.

Problem: Als gepackte .exe (PyInstaller) darf sich die Anwendung nicht auf das
aktuelle Arbeitsverzeichnis verlassen. Beim Autostart ueber die Registry ist
das Arbeitsverzeichnis z. B. oft C:\\Windows\\System32 - dort duerfen/sollen
keine config.json oder Logdateien landen.

Loesung:
- Als .exe (sys.frozen): Daten liegen in %APPDATA%\\AutoCloseV8
  (z. B. C:\\Users\\<Name>\\AppData\\Roaming\\AutoCloseV8). Dieser Ordner ist
  immer beschreibbar, egal wo die .exe liegt (Desktop, Downloads, USB-Stick).
- Als Python-Skript: Daten liegen wie bisher im Projektordner (neben main.py),
  damit sich beim Entwickeln nichts aendert.
"""

import os
import shutil
import sys


def is_frozen() -> bool:
    """True, wenn die Anwendung als gepackte .exe (PyInstaller) laeuft."""
    return bool(getattr(sys, "frozen", False))


def get_app_dir() -> str:
    """
    Liefert das Verzeichnis, in dem Konfiguration und Logs gespeichert werden.
    Das Verzeichnis wird bei Bedarf angelegt.
    """
    if is_frozen():
        base = os.environ.get("APPDATA")
        if base:
            app_dir = os.path.join(base, "AutoCloseV8")
            os.makedirs(app_dir, exist_ok=True)
            _migrate_old_config(base, app_dir)
        else:
            # Notloesung, falls APPDATA nicht gesetzt ist: neben der .exe.
            app_dir = os.path.dirname(os.path.abspath(sys.executable))
    else:
        # Entwicklungsmodus: Projektordner (eine Ebene ueber src/).
        app_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

    os.makedirs(app_dir, exist_ok=True)
    return app_dir


def _migrate_old_config(appdata_base: str, new_dir: str) -> None:
    """
    Uebernimmt die config.json aus dem alten AutoCloseV7-Ordner, falls der
    neue Ordner noch keine eigene Konfiguration hat. So bleiben alle Listen
    und Einstellungen beim Umstieg auf V8 erhalten.
    """
    new_config = os.path.join(new_dir, "config.json")
    if os.path.exists(new_config):
        return
    old_config = os.path.join(appdata_base, "AutoCloseV7", "config.json")
    if os.path.exists(old_config):
        try:
            shutil.copy2(old_config, new_config)
        except OSError:
            # Migration ist "best effort" - notfalls startet V8 mit Standardwerten.
            pass


def get_config_path() -> str:
    """Vollstaendiger Pfad zur config.json."""
    return os.path.join(get_app_dir(), "config.json")


def get_log_dir() -> str:
    """Vollstaendiger Pfad zum Log-Verzeichnis (wird bei Bedarf angelegt)."""
    log_dir = os.path.join(get_app_dir(), "logs")
    os.makedirs(log_dir, exist_ok=True)
    return log_dir
