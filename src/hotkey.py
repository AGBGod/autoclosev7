"""
hotkey.py
----------
Registriert einen globalen Hotkey (systemweit, auch wenn das Fenster nicht
fokussiert ist), um die Ueberwachung schnell ein-/auszuschalten.
Nutzt die Bibliothek "keyboard".
"""

import logging
from typing import Callable, Optional

try:
    import keyboard

    PLATFORM_SUPPORTED = True
except ImportError:  # pragma: no cover - tritt nur ausserhalb von Windows auf
    PLATFORM_SUPPORTED = False

logger = logging.getLogger("AutoCloseV8.Hotkey")


class HotkeyManager:
    """Kapselt die Registrierung/Deregistrierung eines globalen Hotkeys."""

    def __init__(self):
        self._current_hotkey: Optional[str] = None
        self._handle = None

    def register(self, hotkey: str, callback: Callable[[], None]) -> bool:
        """
        Registriert `hotkey` (z. B. "ctrl+alt+p") und ruft `callback` bei
        Betaetigung auf. Ein vorher registrierter Hotkey wird automatisch entfernt.
        """
        if not PLATFORM_SUPPORTED:
            logger.warning(
                "Globale Hotkeys benoetigen die 'keyboard'-Bibliothek "
                "(nur unter Windows getestet)."
            )
            return False

        self.unregister()
        try:
            self._handle = keyboard.add_hotkey(hotkey, callback)
            self._current_hotkey = hotkey
            logger.info("Hotkey registriert: %s", hotkey)
            return True
        except (ValueError, ImportError, Exception) as exc:
            logger.error("Hotkey '%s' konnte nicht registriert werden: %s", hotkey, exc)
            return False

    def unregister(self) -> None:
        """Entfernt den aktuell registrierten Hotkey, falls vorhanden."""
        if not PLATFORM_SUPPORTED or self._handle is None:
            return
        try:
            keyboard.remove_hotkey(self._handle)
            logger.info("Hotkey entfernt: %s", self._current_hotkey)
        except (KeyError, ValueError):
            pass
        finally:
            self._handle = None
            self._current_hotkey = None
