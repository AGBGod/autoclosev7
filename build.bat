@echo off
rem =====================================================================
rem  build.bat - Erstellt AutoCloseV7.exe (eigenstaendig, ohne Python)
rem
rem  Voraussetzung: Python 3.11+ ist auf DIESEM Rechner installiert
rem  (nur zum Bauen - die fertige .exe braucht kein Python mehr).
rem
rem  Nutzung: Doppelklick auf diese Datei oder im Terminal "build.bat".
rem  Ergebnis: dist\AutoCloseV7.exe
rem =====================================================================
setlocal
cd /d "%~dp0"

echo.
echo [1/3] Pruefe Python-Installation ...
where python >nul 2>nul
if errorlevel 1 (
    echo FEHLER: Python wurde nicht gefunden.
    echo Bitte Python 3.11 oder neuer von https://www.python.org/downloads/windows/
    echo installieren und dabei "Add Python to PATH" aktivieren.
    pause
    exit /b 1
)

echo.
echo [2/3] Installiere/aktualisiere Abhaengigkeiten und PyInstaller ...
python -m pip install --upgrade pip >nul
python -m pip install -r requirements.txt pyinstaller
if errorlevel 1 (
    echo FEHLER: Abhaengigkeiten konnten nicht installiert werden.
    pause
    exit /b 1
)

echo.
echo [3/3] Baue AutoCloseV7.exe (das kann 1-2 Minuten dauern) ...
python -m PyInstaller --noconfirm --clean AutoCloseV7.spec
if errorlevel 1 (
    echo FEHLER: Der Build ist fehlgeschlagen. Details siehe Ausgabe oben.
    pause
    exit /b 1
)

echo.
echo =====================================================================
echo  Fertig! Die Datei liegt hier:
echo    %~dp0dist\AutoCloseV7.exe
echo.
echo  Diese eine Datei kann kopiert und auf jedem Windows-10/11-Rechner
echo  per Doppelklick gestartet werden - ohne Python-Installation.
echo =====================================================================
pause
