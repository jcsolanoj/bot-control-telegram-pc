@echo off
title 5. Activar Inicio Automático con Windows
chcp 65001 > nul
cls
echo ==============================================================
echo       ACTIVADOR DE INICIO AUTOMÁTICO CON WINDOWS
echo ==============================================================
echo.
echo Creando acceso directo en tu carpeta de Inicio de Windows...
echo.

powershell -NoProfile -Command ^
    "$wshell = New-Object -ComObject WScript.Shell; " ^
    "$startupFolder = [Environment]::GetFolderPath('Startup'); " ^
    "$shortcutPath = Join-Path $startupFolder 'AsistenteAntigravity.lnk'; " ^
    "$vbsTarget = Join-Path '%~dp0' '4_INICIAR_EN_SEGUNDO_PLANO.vbs'; " ^
    "$shortcut = $wshell.CreateShortcut($shortcutPath); " ^
    "$shortcut.TargetPath = $vbsTarget; " ^
    "$shortcut.WorkingDirectory = '%~dp0'; " ^
    "$shortcut.Description = 'Inicia el Asistente Antigravity en segundo plano al encender la PC'; " ^
    "$shortcut.Save(); " ^
    "Write-Output 'Acceso directo creado exitosamente en: ' $shortcutPath;"

echo.
echo ==============================================================
echo ¡INICIO AUTOMÁTICO ACTIVADO!
echo.
echo Cada vez que enciendas tu PC e inicies sesión, el bot arrancará
echo en segundo plano de manera 100%% invisible.
echo ==============================================================
echo.
pause
