@echo off
:: ============================================================
:: setup.bat — Run this ONCE to register the lgdefect:// protocol
:: Put this file in the SAME folder as autologin.py
:: After running, Submit Defect in the dashboard auto-launches autologin.py
:: ============================================================

SET SCRIPT_DIR=%~dp0
SET AUTOLOGIN=%SCRIPT_DIR%autologin.py
SET LAUNCHER=%SCRIPT_DIR%launch_autologin.bat

:: Write the launcher batch file
(
  echo @echo off
  echo start "" /B pythonw "%AUTOLOGIN%"
) > "%LAUNCHER%"

:: Register lgdefect:// as a Windows URL protocol pointing to launcher
REG ADD "HKCU\Software\Classes\lgdefect" /ve /d "URL:LG Defect Protocol" /f
REG ADD "HKCU\Software\Classes\lgdefect" /v "URL Protocol" /d "" /f
REG ADD "HKCU\Software\Classes\lgdefect\shell\open\command" /ve /d "\"%LAUNCHER%\" \"%%1\"" /f

echo.
echo  ✅  Done! lgdefect:// protocol registered.
echo.
echo  Now open Dash_final.html in Chrome/Edge.
echo  Click Submit Defect — autologin.py will run automatically.
echo.
pause
