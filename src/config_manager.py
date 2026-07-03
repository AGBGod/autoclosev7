"""
config_manager.py
------------------
Verwaltet das Laden, Speichern und Validieren der Konfigurationsdatei (config.json).
Alle Einstellungen der Anwendung (Zielprogramme, Pruefintervall, Autostart, Hotkey usw.)
werden zentral ueber diese Klasse verwaltet und automatisch persistiert.
"""

import json
import logging
import os
import threading
from typing import Any, Dict, List, Optional

from src.paths import get_config_path

logger = logging.getLogger("AutoCloseV8.Config")

# Standardwerte fuer eine Automatik-Sektion (OPEN bzw. CLOSE).
DEFAULT_AUTO_SECTION: Dict[str, Any] = {
    "interval_value": 2.0,
    "interval_unit": "s",
    "interval_seconds": 2.0,
    "after_start": False,
    "after_restart": False,
}

# Standardwerte, falls keine config.json existiert oder Schluessel fehlen.
DEFAULT_CONFIG: Dict[str, Any] = {
    "targets": {
        "window_titles": ["Update Available", "Adobe Flash Player Settings"],
        "process_names": [],
    },
    "open_programs": [],
    "open_auto": dict(DEFAULT_AUTO_SECTION),
    "close_auto": dict(DEFAULT_AUTO_SECTION),
    "check_interval_seconds": 2.0,
    "check_interval_value": 2.0,
    "check_interval_unit": "s",
    "autostart_enabled": False,
    "hotkey": "ctrl+alt+p",
    "monitoring_enabled_on_start": False,
    "close_method": "graceful",
    "minimize_to_tray_on_close": True,
}


class ConfigManager:
    """
    Kapselt den Zugriff auf die Konfigurationsdatei.

    Die Klasse ist thread-sicher, da sowohl die GUI (Haupt-Thread) als auch der
    Ueberwachungs-Thread gleichzeitig auf die Konfiguration zugreifen koennen.
    """

    def __init__(self, config_path: Optional[str] = None):
        # Standard: fester, beschreibbarer Pfad (unabhaengig vom Arbeitsverzeichnis).
        # Als .exe: %APPDATA%\AutoCloseV8\config.json - als Skript: Projektordner.
        self._config_path = config_path or get_config_path()
        self._lock = threading.RLock()
        self._data: Dict[str, Any] = {}
        self.load()

    def load(self) -> None:
        """Laedt die Konfiguration von der Festplatte oder erstellt eine Standarddatei."""
        with self._lock:
            if not os.path.exists(self._config_path):
                logger.info("Keine config.json gefunden - erstelle Standardkonfiguration.")
                self._data = json.loads(json.dumps(DEFAULT_CONFIG))  # tiefe Kopie
                self.save()
                return
            try:
                with open(self._config_path, "r", encoding="utf-8") as f:
                    loaded = json.load(f)
                # Fehlende Schluessel mit Standardwerten auffuellen (Vorwaertskompatibilitaet).
                merged = json.loads(json.dumps(DEFAULT_CONFIG))
                merged.update(loaded)
                # Migration alter Einstellungen: frueher gab es nur EIN Intervall
                # und EIN "Automatik nach Start" (fuer das Schliessen).
                if "close_auto" not in loaded:
                    merged["close_auto"] = dict(DEFAULT_AUTO_SECTION)
                    merged["close_auto"]["interval_value"] = merged.get("check_interval_value", 2.0)
                    merged["close_auto"]["interval_unit"] = merged.get("check_interval_unit", "s")
                    merged["close_auto"]["interval_seconds"] = merged.get("check_interval_seconds", 2.0)
                    merged["close_auto"]["after_start"] = bool(
                        merged.get("monitoring_enabled_on_start", False)
                    )
                self._data = merged
                logger.info("Konfiguration erfolgreich geladen aus %s", self._config_path)
            except (json.JSONDecodeError, OSError) as exc:
                logger.error("Fehler beim Laden der config.json (%s) - verwende Standardwerte.", exc)
                self._data = json.loads(json.dumps(DEFAULT_CONFIG))

    def save(self) -> None:
        """Speichert die aktuelle Konfiguration atomar auf die Festplatte."""
        with self._lock:
            tmp_path = f"{self._config_path}.tmp"
            try:
                with open(tmp_path, "w", encoding="utf-8") as f:
                    json.dump(self._data, f, indent=4, ensure_ascii=False)
                os.replace(tmp_path, self._config_path)
                logger.debug("Konfiguration gespeichert.")
            except OSError as exc:
                logger.error("Konfiguration konnte nicht gespeichert werden: %s", exc)

    def get(self, key: str, default: Any = None) -> Any:
        """Liest einen einzelnen Konfigurationswert."""
        with self._lock:
            return self._data.get(key, default)

    def set(self, key: str, value: Any, autosave: bool = True) -> None:
        """Setzt einen Konfigurationswert und speichert ihn standardmaessig sofort."""
        with self._lock:
            self._data[key] = value
        if autosave:
            self.save()

    @property
    def window_titles(self) -> List[str]:
        """Liste der zu ueberwachenden Fenstertitel (Teilstring-Vergleich)."""
        with self._lock:
            return list(self._data["targets"].get("window_titles", []))

    @property
    def process_names(self) -> List[str]:
        """Liste der zu ueberwachenden Prozessnamen (z. B. 'notepad.exe')."""
        with self._lock:
            return list(self._data["targets"].get("process_names", []))

    def get_auto_section(self, name: str) -> Dict[str, Any]:
        """
        Liefert die Automatik-Einstellungen einer Sektion ('open_auto' oder
        'close_auto') - fehlende Werte werden mit Standardwerten aufgefuellt.
        """
        with self._lock:
            section = dict(DEFAULT_AUTO_SECTION)
            stored = self._data.get(name)
            if isinstance(stored, dict):
                section.update(stored)
            return section

    def set_auto_section(self, name: str, **values: Any) -> None:
        """Aktualisiert einzelne Werte einer Automatik-Sektion und speichert."""
        with self._lock:
            section = self._data.setdefault(name, dict(DEFAULT_AUTO_SECTION))
            section.update(values)
        self.save()

    @property
    def open_programs(self) -> List[str]:
        """Liste der Programme (Pfade), die ueber den Open-Knopf gestartet werden."""
        with self._lock:
            return list(self._data.get("open_programs", []))

    def add_open_program(self, path: str) -> None:
        """Fuegt ein Programm zur OPEN-Liste hinzu."""
        with self._lock:
            programs = self._data.setdefault("open_programs", [])
            if path and path not in programs:
                programs.append(path)
        self.save()

    def remove_open_program(self, path: str) -> None:
        """Entfernt ein Programm aus der OPEN-Liste."""
        with self._lock:
            programs = self._data.setdefault("open_programs", [])
            if path in programs:
                programs.remove(path)
        self.save()

    def add_window_title(self, title: str) -> None:
        """Fuegt einen neuen Fenstertitel zur Zielliste hinzu."""
        with self._lock:
            titles = self._data["targets"].setdefault("window_titles", [])
            if title and title not in titles:
                titles.append(title)
        self.save()

    def remove_window_title(self, title: str) -> None:
        """Entfernt einen Fenstertitel aus der Zielliste."""
        with self._lock:
            titles = self._data["targets"].setdefault("window_titles", [])
            if title in titles:
                titles.remove(title)
        self.save()

    def add_process_name(self, name: str) -> None:
        """Fuegt einen neuen Prozessnamen zur Zielliste hinzu."""
        with self._lock:
            names = self._data["targets"].setdefault("process_names", [])
            if name and name not in names:
                names.append(name)
        self.save()

    def remove_process_name(self, name: str) -> None:
        """Entfernt einen Prozessnamen aus der Zielliste."""
        with self._lock:
            names = self._data["targets"].setdefault("process_names", [])
            if name in names:
                names.remove(name)
        self.save()
