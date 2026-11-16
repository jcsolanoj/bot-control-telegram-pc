@echo off
title 1. Instalar Dependencias del Asistente Antigravity
chcp 65001 > nul
cls
echo ==============================================================
echo       INSTALADOR DE DEPENDENCIAS - ASISTENTE ANTIGRAVITY
echo ==============================================================
echo.
echo Comprobando instalación de Python...
python --version > nul 2>&1
if %ERRORLEVEL% NEQ 0 (
    echo [ERROR] No se detectó Python instalado en el sistema.
    echo Por favor instala Python 3.10 o superior marcando "Add Python to PATH":
    echo https://www.python.org/downloads/
    echo.
    pause
    exit /b 1
)

echo Python detectado correctamente.
echo.
echo Instalando librerías requeridas (python-telegram-bot, google-genai, etc.)...
python -m pip install --upgrade pip
python -m pip install -r "%~dp0core\requirements.txt"
if %ERRORLEVEL% NEQ 0 (
    echo [ERROR] Ocurrió un error instalando los paquetes de Python.
    pause
    exit /b 1
)

echo.
echo Instalando navegadores para automatización web (Playwright Chromium)...
python -m playwright install chromium
if %ERRORLEVEL% NEQ 0 (
    echo [AVISO] No se pudo descargar Chromium automáticamente.
    echo Puedes ejecutar 'python -m playwright install chromium' más tarde si usas navegación web.
)

echo.
echo ==============================================================
echo ¡DEPENDENCIAS INSTALADAS CON ÉXITO!
echo.
echo Siguiente paso: Ejecuta '2_CONFIGURAR_BOT.bat' para vincular
echo tu Token de Telegram y tu clave de Google Gemini.
echo ==============================================================
echo.
pause
