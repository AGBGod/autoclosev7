"""
autostart.py
-------------
Verwaltet den Windows-Autostart ueber die Registry
(HKEY_CURRENT_USER\\Software\\Microsoft\\Windows\\CurrentVersion\\Run).

Es sind keine Administratorrechte noetig, da nur der Registry-Zweig des
aktuellen Benutzers verwendet wird.
"""

import logging
import os
import sys

try:
    import winreg

    PLATFORM_SUPPORTED = True
except ImportError:  # pragma: no cover - tritt nur ausserhalb von Windows auf
    PLATFORM_SUPPORTED = False

logger = logging.getLogger("AutoCloseV8.Autostart")

REGISTRY_PATH = r"Software\Microsoft\Windows\CurrentVersion\Run"
APP_NAME = "AutoCloseV8"
# Alter Eintragsname aus frueheren Versionen - wird automatisch entfernt,
# damit nicht zwei Versionen gleichzeitig starten.
LEGACY_APP_NAMES = ("AutoCloseV7",)


class AutostartManager:
    """Aktiviert/deaktiviert den automatischen Start von AutoCloseV8 mit Windows."""

    @staticmethod
    def _get_executable_command() -> str:
        """
        Ermittelt den Befehl, mit dem die Anwendung beim Systemstart gestartet
        werden soll. Der Parameter --autostart signalisiert der App, dass sie
        von Windows (nach einem Neustart) gestartet wurde - so koennen die
        "nach Neustart"-Automatiken gezielt aktiviert werden.
        """
        if getattr(sys, "frozen", False):
            # Als .exe gepackt (z. B. mit PyInstaller).
            return f'"{sys.executable}" --autostart'
        # Als Python-Skript gestartet.
        script_path = os.path.abspath(sys.argv[0])
        return f'"{sys.executable}" "{script_path}" --autostart'

    def is_enabled(self) -> bool:
        """Prueft, ob der Autostart-Eintrag aktuell in der Registry vorhanden ist."""
        if not PLATFORM_SUPPORTED:
            return False
        try:
            with winreg.OpenKey(
                winreg.HKEY_CURRENT_USER, REGISTRY_PATH, 0, winreg.KEY_READ
            ) as key:
                winreg.QueryValueEx(key, APP_NAME)
                return True
        except FileNotFoundError:
            return False
        except OSError as exc:
            logger.error("Fehler beim Pruefen des Autostart-Status: %s", exc)
            return False

    @staticmethod
    def _remove_legacy_entries() -> None:
        """Entfernt Autostart-Eintraege aelterer Versionen (z. B. AutoCloseV7)."""
        for legacy_name in LEGACY_APP_NAMES:
            try:
                with winreg.OpenKey(
                    winreg.HKEY_CURRENT_USER, REGISTRY_PATH, 0, winreg.KEY_SET_VALUE
                ) as key:
                    winreg.DeleteValue(key, legacy_name)
                logger.info("Alten Autostart-Eintrag entfernt: %s", legacy_name)
            except FileNotFoundError:
                pass  # Kein alter Eintrag vorhanden.
            except OSError as exc:
                logger.debug("Alter Eintrag '%s' nicht entfernbar: %s", legacy_name, exc)

    def enable(self) -> bool:
        """Traegt AutoCloseV8 in den Windows-Autostart ein."""
        if not PLATFORM_SUPPORTED:
            logger.warning("Autostart wird nur unter Windows unterstuetzt.")
            return False
        try:
            command = self._get_executable_command()
            with winreg.OpenKey(
                winreg.HKEY_CURRENT_USER, REGISTRY_PATH, 0, winreg.KEY_SET_VALUE
            ) as key:
                winreg.SetValueEx(key, APP_NAME, 0, winreg.REG_SZ, command)
            self._remove_legacy_entries()
            logger.info("Autostart aktiviert (%s).", command)
            return True
        except OSError as exc:
            logger.error("Autostart konnte nicht aktiviert werden: %s", exc)
            return False

    def disable(self) -> bool:
        """Entfernt AutoCloseV8 aus dem Windows-Autostart."""
        if not PLATFORM_SUPPORTED:
            return False
        try:
            with winreg.OpenKey(
                winreg.HKEY_CURRENT_USER, REGISTRY_PATH, 0, winreg.KEY_SET_VALUE
            ) as key:
                winreg.DeleteValue(key, APP_NAME)
            self._remove_legacy_entries()
            logger.info("Autostart deaktiviert.")
            return True
        except FileNotFoundError:
            self._remove_legacy_entries()
            return True  # War bereits deaktiviert.
        except OSError as exc:
            logger.error("Autostart konnte nicht deaktiviert werden: %s", exc)
            return False

    def set_enabled(self, enabled: bool) -> bool:
        """Aktiviert oder deaktiviert den Autostart abhaengig von `enabled`."""
        return self.enable() if enabled else self.disable()
