"""
Comprueba el estado del Asistente Telegram con confirmación limpia.
"""
import sys
import tkinter as tk
from tkinter import messagebox
import psutil

def get_running_pid():
    for proc in psutil.process_iter(['pid', 'name', 'cmdline']):
        try:
            cmd = proc.info.get('cmdline')
            if cmd and "bot.py" in " ".join(cmd) and ("python" in proc.info.get('name', '').lower()):
                return proc.pid
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    return None

root = tk.Tk()
root.withdraw() # Ocultar ventana principal

pid = get_running_pid()

if pid:
    messagebox.showinfo(
        "Estado del Asistente",
        f"🟢 ESTADO: EN LÍNEA / ACTIVO\n\n"
        f"• PID: {pid}\n"
        f"• El bot está escuchando en Telegram.\n"
        f"• Modo suspensión (Away Mode) activo."
    )
else:
    messagebox.showinfo(
        "Estado del Asistente",
        "🔴 ESTADO: APAGADO / DETENIDO\n\n"
        "• El bot no está en ejecución.\n"
        "• Puedes encenderlo con 'Encender Asistente Telegram'."
    )
