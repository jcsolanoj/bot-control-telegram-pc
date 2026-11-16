"""
Enciende el Asistente Telegram en segundo plano con confirmación limpia.
"""
import os
import sys
import subprocess
import time
import tkinter as tk
from tkinter import messagebox
import psutil

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
BOT_SCRIPT = os.path.join(BASE_DIR, "bot.py")
PYTHONW_EXE = r"C:\Python314\pythonw.exe"
if not os.path.exists(PYTHONW_EXE):
    PYTHONW_EXE = sys.executable.replace("python.exe", "pythonw.exe")

def is_running():
    for proc in psutil.process_iter(['pid', 'name', 'cmdline']):
        try:
            cmd = proc.info.get('cmdline')
            if cmd and "bot.py" in " ".join(cmd) and ("python" in proc.info.get('name', '').lower()):
                return True
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    return False

root = tk.Tk()
root.withdraw() # Ocultar ventana principal

if is_running():
    messagebox.showinfo("Asistente Telegram", "ℹ️ El Asistente ya está ENCENDIDO y escuchando en Telegram.")
    sys.exit(0)

CREATE_NO_WINDOW = 0x08000000
DETACHED_PROCESS = 0x00000008
subprocess.Popen(
    [PYTHONW_EXE, BOT_SCRIPT],
    cwd=BASE_DIR,
    creationflags=CREATE_NO_WINDOW | DETACHED_PROCESS,
    close_fds=True
)

time.sleep(1)

if is_running():
    messagebox.showinfo(
        "Asistente Telegram",
        "🟢 Asistente Telegram ENCENDIDO con éxito.\n\n"
        "Está activo en segundo plano y listo para recibir órdenes por Telegram."
    )
else:
    messagebox.showwarning(
        "Asistente Telegram",
        "⚠️ No se pudo verificar el arranque del bot. Revisa bot.log."
    )
