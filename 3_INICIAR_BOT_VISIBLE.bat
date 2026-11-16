@echo off
title 3. Iniciar Asistente (Modo Visible)
chcp 65001 > nul
cls
echo ==============================================================
echo       INICIANDO ASISTENTE ANTIGRAVITY (MODO CONSOLA VISIBLE)
echo ==============================================================
echo.
echo Presiona Ctrl + C en esta ventana cuando desees detenerlo.
echo.
cd /d "%~dp0core"
if not exist ".env" (
    echo [ERROR] No se encontró el archivo core\.env.
    echo Por favor ejecuta primero '2_CONFIGURAR_BOT.bat'.
    echo.
    pause
    exit /b 1
)

python bot.py
if %ERRORLEVEL% NEQ 0 (
    echo.
    echo [AVISO] El proceso se ha detenido.
    pause
)
