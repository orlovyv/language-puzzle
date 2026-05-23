@echo off
cd /d "%~dp0"

set "PYTHON_EXE=C:\Users\Yuri\AppData\Local\Programs\Python\Python311\python.exe"
set "PORT=3000"

if not exist "%PYTHON_EXE%" (
    echo Python not found: %PYTHON_EXE%
    pause
    exit /b 1
)

set "PORT_PID="
for /f "tokens=5" %%P in ('netstat -ano ^| findstr /R /C:":%PORT% .*LISTENING"') do set "PORT_PID=%%P"

if defined PORT_PID (
    echo Port %PORT% is already in use by process %PORT_PID%.
    echo Close the existing server window or run:
    echo taskkill /PID %PORT_PID% /F
    pause
    exit /b 1
)

"%PYTHON_EXE%" "%~dp0run.py"
if errorlevel 1 (
    echo.
    echo Server stopped with error code %ERRORLEVEL%.
    pause
)
