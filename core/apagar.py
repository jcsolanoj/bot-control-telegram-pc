"""
Apaga el Asistente Telegram con confirmación limpia.
"""
import sys
import tkinter as tk
from tkinter import messagebox
import psutil

def stop_bot():
    count = 0
    for proc in psutil.process_iter(['pid', 'name', 'cmdline']):
        try:
            cmd = proc.info.get('cmdline')
            if cmd and "bot.py" in " ".join(cmd) and ("python" in proc.info.get('name', '').lower()):
                proc.terminate()
                count += 1
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    return count

root = tk.Tk()
root.withdraw() # Ocultar ventana principal

stopped = stop_bot()

if stopped > 0:
    messagebox.showinfo(
        "Asistente Telegram",
        "🔴 Asistente Telegram APAGADO.\n\n"
        "El proceso se ha detenido completamente."
    )
else:
    messagebox.showinfo(
        "Asistente Telegram",
        "ℹ️ El Asistente ya se encontraba apagado."
    )
