@echo off
:: Research Agent — Windows setup launcher
:: Double-click este archivo para instalar todo.
:: Requiere Python 3.10+ instalado y en el PATH.

echo Research Agent Setup
echo.

:: Verificar Python
python --version >nul 2>&1
if errorlevel 1 (
    echo ERROR: Python no encontrado en el PATH.
    echo Descargalo desde https://www.python.org/downloads/
    echo Asegurate de marcar "Add Python to PATH" durante la instalacion.
    pause
    exit /b 1
)

:: Ejecutar setup cross-platform
python "%~dp0setup.py"

echo.
pause
