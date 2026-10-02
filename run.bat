@echo off
REM eml2md launcher - uses the bundled venv python
chcp 65001 >nul
setlocal
set "PY=%~dp0.venv\Scripts\python.exe"
"%PY%" "%~dp0eml2md.py" %*
endlocal
