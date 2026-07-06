"""
admin_autostart.py
-------------------
Richtet AutoCloseV9.0 so ein, dass es beim Anmelden automatisch MIT
Administrator-Rechten startet - ohne dass der Nutzer jedes Mal
"Als Administrator ausfuehren" anklicken oder die UAC-Abfrage bestaetigen muss.

Warum ein "geplanter Task" (Windows-Aufgabenplanung) und nicht der normale
Autostart?
  - Der normale Autostart (Registry HKCU\\...\\Run) kann ein Programm NICHT
    mit erhoehten Rechten starten. Wuerde man die .exe fest auf
    "immer als Administrator" stellen (Manifest requireAdministrator), blockiert
    Windows den Registry-Autostart komplett - die App startet dann gar nicht
    mehr von selbst.
  - Ein geplanter Task mit "Mit hoechsten Berechtigungen ausfuehren"
    (RunLevel = HighestAvailable) und Ausloeser "Bei Anmeldung" startet die App
    dagegen automatisch erhoeht, ganz ohne UAC-Nachfrage.

Das Anlegen/Loeschen des Tasks selbst benoetigt einmalig Administrator-Rechte.
Laeuft die App bereits erhoeht, wird schtasks direkt ausgefuehrt; andernfalls
wird nur der schtasks-Befehl kurz per UAC erhoeht (die App selbst muss dafuer
nicht neu gestartet werden).
"""

import getpass
import logging
import os
import subprocess
import sys
import tempfile
from xml.sax.saxutils import escape

PLATFORM_SUPPORTED = sys.platform == "win32"

# Verhindert, dass beim Aufruf von schtasks kurz ein schwarzes Konsolenfenster
# aufblitzt (die App laeuft als Fenster-Programm ohne Konsole).
_CREATE_NO_WINDOW = 0x08000000

logger = logging.getLogger("AutoCloseV9.0.AdminAutostart")

TASK_NAME = "AutoCloseV9.0"
# Namen geplanter Tasks aus frueheren Versionen - werden beim Umstellen des
# Administrator-Starts automatisch entfernt, damit nach einem Upgrade nicht
# zwei Versionen gleichzeitig erhoeht starten.
LEGACY_TASK_NAMES = ("AutoCloseV8",)


class AdminAutostartManager:
    """Verwaltet den geplanten Task fuer den automatischen Administrator-Start."""

    # ------------------------------------------------------------------
    # Statusabfragen
    # ------------------------------------------------------------------
    @staticmethod
    def is_admin() -> bool:
        """Prueft, ob die App aktuell mit Administrator-Rechten laeuft."""
        if not PLATFORM_SUPPORTED:
            return False
        try:
            import ctypes

            return bool(ctypes.windll.shell32.IsUserAnAdmin())
        except Exception:  # pragma: no cover - nur unter Windows relevant
            return False

    def is_enabled(self) -> bool:
        """Prueft, ob der geplante Task bereits vorhanden ist."""
        if not PLATFORM_SUPPORTED:
            return False
        return self._task_exists(TASK_NAME)

    @staticmethod
    def _task_exists(name: str) -> bool:
        """Prueft, ob ein geplanter Task mit dem gegebenen Namen existiert."""
        try:
            result = subprocess.run(
                ["schtasks", "/Query", "/TN", name],
                capture_output=True,
                creationflags=_CREATE_NO_WINDOW,
            )
            return result.returncode == 0
        except OSError as exc:
            logger.debug("schtasks /Query fehlgeschlagen: %s", exc)
            return False

    # ------------------------------------------------------------------
    # Aktivieren / Deaktivieren
    # ------------------------------------------------------------------
    def enable(self) -> bool:
        """
        Legt den geplanten Task an (Ausloeser: Anmeldung, mit hoechsten
        Berechtigungen). Liefert True bei Erfolg.
        """
        if not PLATFORM_SUPPORTED:
            logger.warning("Automatischer Administrator-Start nur unter Windows moeglich.")
            return False

        xml = self._build_task_xml()
        # schtasks erwartet die XML-Datei in UTF-16.
        tmp_path = os.path.join(tempfile.gettempdir(), "autoclosev9_task.xml")
        try:
            with open(tmp_path, "w", encoding="utf-16") as f:
                f.write(xml)
        except OSError as exc:
            logger.error("Task-Definition konnte nicht geschrieben werden: %s", exc)
            return False

        try:
            ok = self._run_schtasks(["/Create", "/TN", TASK_NAME, "/XML", tmp_path, "/F"])
        finally:
            try:
                os.remove(tmp_path)
            except OSError:
                pass

        if ok:
            logger.info("Geplanter Task fuer Administrator-Start angelegt.")
            self.remove_legacy_tasks(allow_uac=True)
        return ok

    def disable(self) -> bool:
        """Entfernt den geplanten Task wieder. Liefert True bei Erfolg."""
        if not PLATFORM_SUPPORTED:
            return False
        ok = True
        if self.is_enabled():
            ok = self._run_schtasks(["/Delete", "/TN", TASK_NAME, "/F"])
            if ok:
                logger.info("Geplanter Task fuer Administrator-Start entfernt.")
        # Auch geplante Tasks frueherer Versionen entfernen.
        self.remove_legacy_tasks(allow_uac=True)
        return ok

    def remove_legacy_tasks(self, allow_uac: bool = False) -> None:
        """
        Entfernt geplante Tasks aelterer Versionen (z. B. AutoCloseV8), damit
        nach einem Upgrade nicht zwei Versionen gleichzeitig erhoeht starten.

        allow_uac=False: nur loeschen, wenn die App ohnehin schon erhoeht laeuft
        (dann ohne zusaetzliche UAC-Abfrage). allow_uac=True: bei Bedarf einmalig
        per UAC erhoehen - das passiert nur, wenn wirklich noch ein alter Task
        vorhanden ist.
        """
        if not PLATFORM_SUPPORTED:
            return
        for name in LEGACY_TASK_NAMES:
            if not self._task_exists(name):
                continue
            if not allow_uac and not self.is_admin():
                continue
            if self._run_schtasks(["/Delete", "/TN", name, "/F"]):
                logger.info("Alten geplanten Task entfernt: %s", name)

    # ------------------------------------------------------------------
    # Interne Helfer
    # ------------------------------------------------------------------
    def _run_schtasks(self, args) -> bool:
        """
        Fuehrt schtasks mit den gegebenen Argumenten aus. Laeuft die App bereits
        als Administrator, direkt; andernfalls wird nur der schtasks-Befehl per
        UAC erhoeht und auf sein Ende gewartet.
        """
        if self.is_admin():
            try:
                result = subprocess.run(
                    ["schtasks", *args],
                    capture_output=True,
                    creationflags=_CREATE_NO_WINDOW,
                )
                if result.returncode != 0:
                    logger.error(
                        "schtasks fehlgeschlagen (%s): %s",
                        result.returncode,
                        result.stderr.decode("utf-8", errors="ignore").strip(),
                    )
                return result.returncode == 0
            except OSError as exc:
                logger.error("schtasks konnte nicht gestartet werden: %s", exc)
                return False

        code = self._run_elevated_and_wait("schtasks.exe", subprocess.list2cmdline(args))
        if code is None:
            logger.info("Administrator-Freigabe wurde abgebrochen oder schlug fehl.")
            return False
        if code != 0:
            logger.error("schtasks (erhoeht) endete mit Code %s.", code)
        return code == 0

    @staticmethod
    def _run_elevated_and_wait(exe: str, params: str):
        """
        Startet `exe` mit `params` erhoeht (UAC) und wartet auf das Ende.
        Liefert den Exit-Code oder None, wenn der Start fehlschlug/abgebrochen wurde.
        """
        try:
            import ctypes
            from ctypes import wintypes

            class SHELLEXECUTEINFOW(ctypes.Structure):
                _fields_ = [
                    ("cbSize", wintypes.DWORD),
                    ("fMask", ctypes.c_ulong),
                    ("hwnd", wintypes.HWND),
                    ("lpVerb", wintypes.LPCWSTR),
                    ("lpFile", wintypes.LPCWSTR),
                    ("lpParameters", wintypes.LPCWSTR),
                    ("lpDirectory", wintypes.LPCWSTR),
                    ("nShow", ctypes.c_int),
                    ("hInstApp", wintypes.HINSTANCE),
                    ("lpIDList", ctypes.c_void_p),
                    ("lpClass", wintypes.LPCWSTR),
                    ("hkeyClass", wintypes.HKEY),
                    ("dwHotKey", wintypes.DWORD),
                    ("hIcon", wintypes.HANDLE),
                    ("hProcess", wintypes.HANDLE),
                ]

            SEE_MASK_NOCLOSEPROCESS = 0x00000040
            SEE_MASK_NO_CONSOLE = 0x00008000
            SW_HIDE = 0
            INFINITE_TIMEOUT_MS = 60000

            sei = SHELLEXECUTEINFOW()
            sei.cbSize = ctypes.sizeof(sei)
            sei.fMask = SEE_MASK_NOCLOSEPROCESS | SEE_MASK_NO_CONSOLE
            sei.lpVerb = "runas"
            sei.lpFile = exe
            sei.lpParameters = params
            sei.nShow = SW_HIDE

            if not ctypes.windll.shell32.ShellExecuteExW(ctypes.byref(sei)):
                return None  # z. B. UAC abgebrochen (ERROR_CANCELLED).
            if not sei.hProcess:
                return None

            ctypes.windll.kernel32.WaitForSingleObject(sei.hProcess, INFINITE_TIMEOUT_MS)
            code = wintypes.DWORD()
            ctypes.windll.kernel32.GetExitCodeProcess(sei.hProcess, ctypes.byref(code))
            ctypes.windll.kernel32.CloseHandle(sei.hProcess)
            return int(code.value)
        except Exception as exc:  # pragma: no cover - nur unter Windows relevant
            logger.error("Erhoehter Aufruf fehlgeschlagen: %s", exc)
            return None

    @staticmethod
    def _current_user() -> str:
        """Ermittelt den aktuellen Benutzer als 'DOMAENE\\Name'."""
        domain = os.environ.get("USERDOMAIN", "")
        try:
            user = os.environ.get("USERNAME") or getpass.getuser()
        except Exception:
            user = os.environ.get("USERNAME", "")
        return f"{domain}\\{user}" if domain else user

    @staticmethod
    def _executable_command():
        """Liefert (Programm, Argumente) fuer die Task-Aktion."""
        if getattr(sys, "frozen", False):
            return sys.executable, "--autostart"
        script = os.path.abspath(sys.argv[0])
        return sys.executable, f'"{script}" --autostart'

    def _build_task_xml(self) -> str:
        """Baut die XML-Definition des geplanten Tasks."""
        command, arguments = self._executable_command()
        user = self._current_user()
        return (
            '<?xml version="1.0" encoding="UTF-16"?>\n'
            '<Task version="1.2" '
            'xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">\n'
            "  <RegistrationInfo>\n"
            "    <Description>Startet AutoCloseV9.0 beim Anmelden mit "
            "Administrator-Rechten.</Description>\n"
            "  </RegistrationInfo>\n"
            "  <Triggers>\n"
            "    <LogonTrigger>\n"
            "      <Enabled>true</Enabled>\n"
            f"      <UserId>{escape(user)}</UserId>\n"
            "    </LogonTrigger>\n"
            "  </Triggers>\n"
            "  <Principals>\n"
            '    <Principal id="Author">\n'
            f"      <UserId>{escape(user)}</UserId>\n"
            "      <LogonType>InteractiveToken</LogonType>\n"
            "      <RunLevel>HighestAvailable</RunLevel>\n"
            "    </Principal>\n"
            "  </Principals>\n"
            "  <Settings>\n"
            "    <MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy>\n"
            "    <DisallowStartIfOnBatteries>false</DisallowStartIfOnBatteries>\n"
            "    <StopIfGoingOnBatteries>false</StopIfGoingOnBatteries>\n"
            "    <AllowHardTerminate>true</AllowHardTerminate>\n"
            "    <StartWhenAvailable>false</StartWhenAvailable>\n"
            "    <RunOnlyIfNetworkAvailable>false</RunOnlyIfNetworkAvailable>\n"
            "    <IdleSettings>\n"
            "      <StopOnIdleEnd>false</StopOnIdleEnd>\n"
            "      <RestartOnIdle>false</RestartOnIdle>\n"
            "    </IdleSettings>\n"
            "    <AllowStartOnDemand>true</AllowStartOnDemand>\n"
            "    <Enabled>true</Enabled>\n"
            "    <Hidden>false</Hidden>\n"
            "    <RunOnlyIfIdle>false</RunOnlyIfIdle>\n"
            "    <WakeToRun>false</WakeToRun>\n"
            "    <ExecutionTimeLimit>PT0S</ExecutionTimeLimit>\n"
            "    <Priority>7</Priority>\n"
            "  </Settings>\n"
            '  <Actions Context="Author">\n'
            "    <Exec>\n"
            f"      <Command>{escape(command)}</Command>\n"
            f"      <Arguments>{escape(arguments)}</Arguments>\n"
            "    </Exec>\n"
            "  </Actions>\n"
            "</Task>\n"
        )
