"""
Control del Asistente Telegram.
Permite ver el estado en tiempo real, encenderlo o apagarlo en un solo clic.
"""

import os
import sys
import shutil
import subprocess
import tkinter as tk
from tkinter import messagebox
import psutil

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
BOT_SCRIPT = os.path.join(BASE_DIR, "bot.py")
PYTHONW_EXE = sys.executable.replace("python.exe", "pythonw.exe")
if not os.path.exists(PYTHONW_EXE):
    PYTHONW_EXE = shutil.which("pythonw") or sys.executable


def get_bot_processes():
    """Busca procesos de Python ejecutando bot.py."""
    matching = []
    for proc in psutil.process_iter(['pid', 'name', 'cmdline']):
        try:
            cmd = proc.info.get('cmdline')
            if cmd:
                cmd_str = " ".join(cmd)
                if "bot.py" in cmd_str and ("python" in proc.info.get('name', '').lower()):
                    matching.append(proc)
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    return matching


class BotControlApp:
    def __init__(self, root):
        self.root = root
        self.root.title("Asistente Telegram")
        self.root.geometry("380x250")
        self.root.resizable(False, False)
        
        # Colores
        self.bg_color = "#F8F9FA"
        self.card_bg = "#FFFFFF"
        self.green_color = "#0D904F"
        self.red_color = "#D93025"
        self.text_dark = "#202124"
        self.text_muted = "#5F6368"
        
        self.root.configure(bg=self.bg_color)
        self.root.eval('tk::PlaceWindow . center')

        # Marco Principal
        main_frame = tk.Frame(root, bg=self.bg_color, padx=22, pady=18)
        main_frame.pack(fill=tk.BOTH, expand=True)

        # 1. FUNCIÓN: VER ESTADO (Tarjeta de Estado Visual)
        self.card = tk.Frame(
            main_frame,
            bg=self.card_bg,
            padx=16,
            pady=14,
            highlightbackground="#E0E0E0",
            highlightthickness=1
        )
        self.card.pack(fill=tk.X, pady=(0, 16))

        self.status_icon = tk.Label(
            self.card,
            text="●",
            font=("Segoe UI", 20),
            bg=self.card_bg,
            fg=self.text_muted
        )
        self.status_icon.pack(side=tk.LEFT, padx=(0, 12))

        status_text_frame = tk.Frame(self.card, bg=self.card_bg)
        status_text_frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        self.status_title = tk.Label(
            status_text_frame,
            text="Comprobando...",
            font=("Segoe UI", 12, "bold"),
            bg=self.card_bg,
            fg=self.text_dark,
            anchor="w"
        )
        self.status_title.pack(fill=tk.X)

        self.status_detail = tk.Label(
            status_text_frame,
            text="Verificando procesos en la PC...",
            font=("Segoe UI", 9),
            bg=self.card_bg,
            fg=self.text_muted,
            anchor="w"
        )
        self.status_detail.pack(fill=tk.X)

        # 2. FUNCIÓN: ENCENDER ASISTENTE
        self.btn_start = tk.Button(
            main_frame,
            text="▶ Encender Asistente",
            font=("Segoe UI", 10, "bold"),
            bg=self.green_color,
            fg="white",
            activebackground="#0B8043",
            activeforeground="white",
            relief=tk.FLAT,
            cursor="hand2",
            pady=9,
            command=self.start_bot
        )
        self.btn_start.pack(fill=tk.X, pady=(0, 10))

        # 3. FUNCIÓN: APAGAR ASISTENTE
        self.btn_stop = tk.Button(
            main_frame,
            text="⏹ Apagar Asistente",
            font=("Segoe UI", 10, "bold"),
            bg=self.red_color,
            fg="white",
            activebackground="#C5221F",
            activeforeground="white",
            relief=tk.FLAT,
            cursor="hand2",
            pady=9,
            command=self.stop_bot
        )
        self.btn_stop.pack(fill=tk.X)

        # Actualización automática continua del estado
        self.refresh_status()

    def refresh_status(self):
        procs = get_bot_processes()
        if procs:
            pid = procs[0].pid
            self.status_icon.config(text="●", fg=self.green_color)
            self.status_title.config(text="EN LÍNEA (Activo)", fg=self.green_color)
            self.status_detail.config(text=f"Escuchando en Telegram | PID: {pid}")
            self.btn_start.config(state=tk.DISABLED, bg="#D6D9DC", cursor="arrow")
            self.btn_stop.config(state=tk.NORMAL, bg=self.red_color, cursor="hand2")
        else:
            self.status_icon.config(text="○", fg=self.red_color)
            self.status_title.config(text="APAGADO (Detenido)", fg=self.red_color)
            self.status_detail.config(text="El bot no está en ejecución.")
            self.btn_start.config(state=tk.NORMAL, bg=self.green_color, cursor="hand2")
            self.btn_stop.config(state=tk.DISABLED, bg="#D6D9DC", cursor="arrow")

        # Re-comprobar cada 1.5 segundos automáticamente
        self.root.after(1500, self.refresh_status)

    def start_bot(self):
        procs = get_bot_processes()
        if procs:
            return

        try:
            CREATE_NO_WINDOW = 0x08000000
            wmi_cmd = (
                f'Invoke-CimMethod -ClassName Win32_Process -MethodName Create '
                f'-Arguments @{{CommandLine = \'{PYTHONW_EXE} bot.py\'; CurrentDirectory = \'{BASE_DIR}\'}}'
            )
            res = subprocess.run(
                ["powershell", "-NoProfile", "-Command", wmi_cmd],
                capture_output=True,
                text=True,
                timeout=8,
                creationflags=CREATE_NO_WINDOW
            )
            if res.returncode != 0:
                subprocess.Popen(
                    [PYTHONW_EXE, BOT_SCRIPT],
                    cwd=BASE_DIR,
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    creationflags=CREATE_NO_WINDOW,
                    close_fds=True
                )
            self.root.after(800, self.refresh_status)
        except Exception as e:
            messagebox.showerror("Error", f"No se pudo iniciar el Asistente:\n{e}")

    def stop_bot(self):
        procs = get_bot_processes()
        if not procs:
            return

        for p in procs:
            try:
                p.terminate()
            except Exception:
                pass

        _, alive = psutil.wait_procs(procs, timeout=1.5)
        for p in alive:
            try:
                p.kill()
            except Exception:
                pass
        
        self.root.after(300, self.refresh_status)


if __name__ == "__main__":
    root = tk.Tk()
    app = BotControlApp(root)
    root.mainloop()
