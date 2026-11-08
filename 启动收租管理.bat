@echo off
setlocal
cd /d "%~dp0"
set "PYTHONUTF8=1"
title Rental Manager

where py >nul 2>nul
if not errorlevel 1 goto run_py_launcher

where python >nul 2>nul
if not errorlevel 1 goto run_python

echo.
echo Python 3.10 or newer is required.
echo.
echo Install Python from https://www.python.org/downloads/
pause
exit /b 1

:run_py_launcher
py -3 app.py --port 8848
goto end

:run_python
python app.py --port 8848
goto end

:end
if errorlevel 1 pause
