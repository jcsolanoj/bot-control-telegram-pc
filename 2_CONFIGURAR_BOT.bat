@echo off
title 2. Asistente de Configuracion - Asistente Antigravity
chcp 65001 > nul
cls
echo ==============================================================
echo       ASISTENTE DE CONFIGURACIÓN - VINCULACIÓN DE CUENTAS
echo ==============================================================
echo.
echo Este asistente te ayudará a configurar tu archivo .env de forma
echo guiada y segura.
echo.

set /p BOT_TOKEN="1. Pega tu Token de Telegram Bot (de @BotFather): "
if "%BOT_TOKEN%"=="" (
    echo [ERROR] El Token de Telegram no puede estar vacío.
    pause
    exit /b 1
)

echo.
set /p USER_ID="2. Pega tu ID numérico de Telegram (de @userinfobot): "
if "%USER_ID%"=="" (
    echo [ERROR] El ID de Telegram no puede estar vacío.
    pause
    exit /b 1
)

echo.
set /p GEMINI_KEY="3. Pega tu clave de Google Gemini API (de aistudio.google.com): "
if "%GEMINI_KEY%"=="" (
    echo [ERROR] La clave de Gemini no puede estar vacía.
    pause
    exit /b 1
)

echo.
echo Guardando credenciales en core\.env ...

(
    echo # =====================================================================
    echo # Configuracion del Asistente Telegram ^<^-^> Antigravity / PC
    echo # =====================================================================
    echo.
    echo TELEGRAM_BOT_TOKEN=%BOT_TOKEN%
    echo TELEGRAM_ALLOWED_USER_ID=%USER_ID%
    echo.
    echo GEMINI_API_KEY=%GEMINI_KEY%
    echo GEMINI_MODEL=gemini-4-hydrogen
    echo.
    echo # Credenciales Institucionales / Portales (Opcional)
    echo INSTITUTIONAL_USER=
    echo INSTITUTIONAL_PASSWORD=
    echo INSTITUTIONAL_2FA_SECRET=
) > "%~dp0core\.env"

echo.
echo ==============================================================
echo ¡CONFIGURACIÓN COMPLETADA CON ÉXITO!
echo.
echo Tu archivo core\.env ha sido creado y asegurado.
echo Ya puedes ejecutar '3_INICIAR_BOT_VISIBLE.bat' para hacer una
echo prueba inicial y verificar que responde en tu Telegram.
echo ==============================================================
echo.
pause
