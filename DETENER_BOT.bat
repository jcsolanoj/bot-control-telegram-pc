@echo off
title Detener Asistente Antigravity
chcp 65001 > nul
cls
echo ==============================================================
echo       DETENIENDO PROCESOS DEL ASISTENTE ANTIGRAVITY
echo ==============================================================
echo.
powershell -NoProfile -Command "Get-CimInstance Win32_Process -Filter \"CommandLine like '%%bot.py%%'\" | ForEach-Object { Stop-Process -Id $_.ProcessId -Force; Write-Output \"Proceso detenido: PID $($_.ProcessId)\" }"
echo.
echo Listo. Cualquier instancia del bot ha sido finalizada.
echo.
pause
