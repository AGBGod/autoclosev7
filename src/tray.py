"""
tray.py
--------
System-Tray-Symbol fuer AutoCloseV8. Ermoeglicht es, die Anwendung zu
minimieren, ohne die Ueberwachung zu beenden, und bietet ein Kontextmenue mit
Schnellzugriffen (Anzeigen, Start/Stop, Beenden).
"""

import logging
import threading
from typing import Callable, Optional

try:
    import pystray
    from PIL import Image, ImageDraw

    PLATFORM_SUPPORTED = True
except ImportError:  # pragma: no cover - tritt nur ausserhalb von Windows auf
    PLATFORM_SUPPORTED = False

logger = logging.getLogger("AutoCloseV8.Tray")


def _build_icon_image(active: bool):
    """Erzeugt ein einfaches, programmgesteuertes Icon (kein externes Bild noetig)."""
    size = 64
    color = (80, 200, 120) if active else (200, 80, 80)
    image = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    draw.ellipse((4, 4, size - 4, size - 4), fill=color)
    return image


class TrayIcon:
    """Kapselt das pystray-Icon inklusive Kontextmenue in einem eigenen Thread."""

    def __init__(
        self,
        on_toggle: Callable[[], None],
        on_show: Callable[[], None],
        on_quit: Callable[[], None],
        is_running: Callable[[], bool],
    ):
        self._on_toggle = on_toggle
        self._on_show = on_show
        self._on_quit = on_quit
        self._is_running = is_running
        self._icon = None
        self._thread: Optional[threading.Thread] = None

    def _menu(self):
        return pystray.Menu(
            pystray.MenuItem("Anzeigen", lambda: self._on_show()),
            pystray.MenuItem("Start/Stop", lambda: self._on_toggle()),
            pystray.MenuItem("Beenden", lambda: self._on_quit()),
        )

    def start(self) -> None:
        """Startet das Tray-Icon in einem eigenen Hintergrund-Thread."""
        if not PLATFORM_SUPPORTED:
            logger.warning(
                "Tray-Icon benoetigt 'pystray' und 'Pillow' (nur unter Windows getestet)."
            )
            return
        self._icon = pystray.Icon(
            "AutoCloseV8",
            icon=_build_icon_image(self._is_running()),
            title="AutoCloseV8",
            menu=self._menu(),
        )
        self._thread = threading.Thread(target=self._icon.run, name="TrayIconThread", daemon=True)
        self._thread.start()
        logger.info("Tray-Icon gestartet.")

    def refresh_icon(self) -> None:
        """Aktualisiert die Icon-Farbe je nach Ueberwachungsstatus (gruen = aktiv, rot = gestoppt)."""
        if self._icon is not None:
            self._icon.icon = _build_icon_image(self._is_running())

    def stop(self) -> None:
        """Beendet das Tray-Icon sauber."""
        if self._icon is not None:
            self._icon.stop()
            logger.info("Tray-Icon gestoppt.")
