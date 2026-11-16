"""
Módulo de ejecución de tareas complejas mediante Antigravity CLI (agy.exe).
Implementa Windows Job Objects con ctypes para terminación atómica sin procesos huérfanos,
drenado concurrente de pipes anti-deadlock, cola FIFO de ejecución y contratos retrocompatibles.
"""

import os
import sys
import time
import ctypes
from ctypes import wintypes
import subprocess
import threading
import logging
import re
import datetime
from typing import Union, Dict, Any, List

logger = logging.getLogger(__name__)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
TEMP_DIR = os.path.join(BASE_DIR, "temp")
os.makedirs(TEMP_DIR, exist_ok=True)

import shutil

AGY_EXE = shutil.which("agy") or os.path.expanduser(r"~\AppData\Local\agy\bin\agy.exe")

DEFAULT_WORKSPACE = os.path.expanduser(os.environ.get("WORKSPACE_DIR", r"~\Documents"))

# Constantes de la API Win32
JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x00002000
JobObjectExtendedLimitInformation = 9


class IO_COUNTERS(ctypes.Structure):
    _fields_ = [
        ("ReadOperationCount", ctypes.c_uint64),
        ("WriteOperationCount", ctypes.c_uint64),
        ("OtherOperationCount", ctypes.c_uint64),
        ("ReadTransferCount", ctypes.c_uint64),
        ("WriteTransferCount", ctypes.c_uint64),
        ("OtherTransferCount", ctypes.c_uint64),
    ]


class JOBOBJECT_BASIC_LIMIT_INFORMATION(ctypes.Structure):
    _fields_ = [
        ("PerProcessUserTimeLimit", ctypes.c_int64),
        ("PerJobUserTimeLimit", ctypes.c_int64),
        ("LimitFlags", wintypes.DWORD),
        ("MinimumWorkingSetSize", ctypes.c_size_t),
        ("MaximumWorkingSetSize", ctypes.c_size_t),
        ("ActiveProcessLimit", wintypes.DWORD),
        ("Affinity", ctypes.c_size_t),
        ("PriorityClass", wintypes.DWORD),
        ("SchedulingClass", wintypes.DWORD),
    ]


class JOBOBJECT_EXTENDED_LIMIT_INFORMATION(ctypes.Structure):
    _fields_ = [
        ("BasicLimitInformation", JOBOBJECT_BASIC_LIMIT_INFORMATION),
        ("IoInfo", IO_COUNTERS),
        ("ProcessMemoryLimit", ctypes.c_size_t),
        ("JobMemoryLimit", ctypes.c_size_t),
        ("PeakProcessMemoryLimit", ctypes.c_size_t),
        ("PeakJobMemoryLimit", ctypes.c_size_t),
    ]


def _create_win32_job_object() -> int:
    """Crea un Job Object de Windows configurado con auto-terminación de hijos."""
    try:
        kernel32 = ctypes.windll.kernel32
        h_job = kernel32.CreateJobObjectW(None, None)
        if not h_job:
            return 0
        info = JOBOBJECT_EXTENDED_LIMIT_INFORMATION()
        info.BasicLimitInformation.LimitFlags = JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        success = kernel32.SetInformationJobObject(
            h_job,
            JobObjectExtendedLimitInformation,
            ctypes.byref(info),
            ctypes.sizeof(info)
        )
        if not success:
            kernel32.CloseHandle(h_job)
            return 0
        return h_job
    except Exception as e:
        logger.warning(f"No se pudo crear Windows Job Object: {e}")
        return 0


def _assign_process_to_job(h_job: int, proc_handle: int) -> bool:
    """Asigna un proceso al Job Object."""
    if not h_job or not proc_handle:
        return False
    try:
        return bool(ctypes.windll.kernel32.AssignProcessToJobObject(h_job, int(proc_handle)))
    except Exception as e:
        logger.warning(f"Error asignando proceso al Job Object: {e}")
        return False


def _close_handle(handle: int):
    """Cierra un handle Win32 con seguridad."""
    if handle:
        try:
            ctypes.windll.kernel32.CloseHandle(handle)
        except Exception:
            pass


# Cola y control global de ejecución para agy.exe
_AGY_LOCK = threading.Lock()
ACTIVE_JOB_HANDLES: List[int] = []
ACTIVE_PROCESSES: List[subprocess.Popen] = []

# Regex exhaustivo de secuencias de escape ANSI (incluye OSC terminal)
ANSI_ESCAPE_PATTERN = re.compile(r'\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~]|\].*?(?:\x07|\x1B\\))')


def strip_ansi(text: str) -> str:
    """Elimina secuencias de control ANSI de una cadena."""
    if not text:
        return ""
    return ANSI_ESCAPE_PATTERN.sub("", text)


def cancel_running_tasks() -> int:
    """
    Cancela inmediatamente cualquier proceso de agy.exe o worker en ejecución.
    Cierra los Job Objects asociados provocando que el kernel de Windows mate atómicamente
    a agy.exe y todos sus procesos hijos (Git, Node, shells).
    """
    global ACTIVE_JOB_HANDLES, ACTIVE_PROCESSES
    killed = 0

    # 1. Cerrar todos los Job Objects activos (auto-kill atómico en kernel)
    for h_job in list(ACTIVE_JOB_HANDLES):
        _close_handle(h_job)
        killed += 1
    ACTIVE_JOB_HANDLES.clear()

    # 2. Terminación de seguridad para procesos rastreados
    for proc in list(ACTIVE_PROCESSES):
        try:
            if proc.poll() is None:
                proc.kill()
                killed += 1
        except Exception:
            pass
    ACTIVE_PROCESSES.clear()

    # 3. Barrido de seguridad para procesos huérfanos residuales
    try:
        import psutil
        for p in psutil.process_iter(['name', 'cmdline']):
            try:
                name = p.info.get('name', '').lower()
                cmd = p.info.get('cmdline') or []
                if "agy.exe" in name or any("agy.exe" in str(x).lower() for x in cmd):
                    p.kill()
                    killed += 1
            except Exception:
                pass
    except Exception:
        pass

    return killed


def execute_autonomous_task(
    task_description: str,
    work_dir: str = None,
    conversation_id: str = None,
    timeout_seconds: int = 120,
    return_dict: bool = False
) -> Union[str, Dict[str, Any]]:
    """
    Ejecuta una tarea autónoma en Antigravity CLI (agy.exe).
    Mantiene compatibilidad con la firma existente (retorna str por defecto o dict si return_dict=True).
    """
    global ACTIVE_JOB_HANDLES, ACTIVE_PROCESSES

    target_dir = work_dir or DEFAULT_WORKSPACE
    if not os.path.exists(target_dir):
        target_dir = os.getcwd()

    # Resolver sesión si no fue provista explícitamente
    conv_id = conversation_id
    if not conv_id:
        try:
            import project_manager
            _, resolved_dir, conv_id = project_manager.resolve_project_session(task_description)
            if not work_dir and resolved_dir and os.path.exists(resolved_dir):
                target_dir = resolved_dir
        except Exception as e:
            logger.warning(f"No se pudo resolver proyecto desde project_manager: {e}")

    # Construir argumentos de agy.exe de forma segura (sin shell=True)
    # -p toma la descripción como argumento directo
    cmd = [
        AGY_EXE,
        "-p", task_description,
        "--dangerously-skip-permissions",
        "--output-format", "text",
        "--model", "gemini-3.8-flash-low",
        "--effort", "low"
    ]

    if conv_id:
        cmd.extend(["--conversation", str(conv_id)])
    if target_dir:
        cmd.extend(["--add-dir", str(target_dir)])

    h_job = 0
    proc = None
    output_text = ""
    generated_files: List[str] = []

    # Serializar mediante lock global para proteger base de datos interna de agy
    with _AGY_LOCK:
        try:
            logger.info(f"Despachando tarea a Antigravity CLI en '{target_dir}'...")
            h_job = _create_win32_job_object()

            proc = subprocess.Popen(
                cmd,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                errors="replace",
                cwd=target_dir,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)
            )

            ACTIVE_PROCESSES.append(proc)
            if h_job and hasattr(proc, "_handle"):
                _assign_process_to_job(h_job, proc._handle)
                ACTIVE_JOB_HANDLES.append(h_job)

            # Drenado anti-deadlock concurrente de stdout y stderr con hilos dedicados
            stdout_chunks = []
            stderr_chunks = []

            def read_pipe(pipe, collector):
                try:
                    for chunk in iter(lambda: pipe.read(4096), ""):
                        if not chunk:
                            break
                        collector.append(chunk)
                except Exception:
                    pass
                finally:
                    try:
                        pipe.close()
                    except Exception:
                        pass

            t_out = threading.Thread(target=read_pipe, args=(proc.stdout, stdout_chunks), daemon=True)
            t_err = threading.Thread(target=read_pipe, args=(proc.stderr, stderr_chunks), daemon=True)
            t_out.start()
            t_err.start()

            # Espera activa controlada con límite de tiempo
            start_time = time.time()
            while time.time() - start_time < timeout_seconds:
                if proc.poll() is not None:
                    break
                time.sleep(0.4)

            if proc.poll() is None:
                # Tiempo excedido: matar Job Object atómicamente
                logger.warning(f"Tarea en agy.exe excedió el límite de {timeout_seconds}s. Cancelando...")
                _close_handle(h_job)
                if h_job in ACTIVE_JOB_HANDLES:
                    ACTIVE_JOB_HANDLES.remove(h_job)
                try:
                    proc.kill()
                except Exception:
                    pass
                output_text = f"⚠️ La tarea excedió el límite de {timeout_seconds} segundos y fue detenida para proteger el sistema."
            else:
                t_out.join(timeout=2.0)
                t_err.join(timeout=2.0)
                raw_stdout = "".join(stdout_chunks).strip()
                raw_stderr = "".join(stderr_chunks).strip()

                clean_out = strip_ansi(raw_stdout)
                clean_err = strip_ansi(raw_stderr)

                if clean_out:
                    output_text = clean_out
                elif clean_err:
                    output_text = clean_err
                else:
                    output_text = "Tarea completada exitosamente por Antigravity."

        except Exception as e:
            logger.error(f"Error ejecutando agy.exe: {e}")
            output_text = f"⚠️ Error al ejecutar Antigravity CLI: {e}"
        finally:
            if h_job:
                _close_handle(h_job)
                if h_job in ACTIVE_JOB_HANDLES:
                    ACTIVE_JOB_HANDLES.remove(h_job)
            if proc and proc in ACTIVE_PROCESSES:
                ACTIVE_PROCESSES.remove(proc)

    # Manejo de salidas extensas (> 8000 caracteres)
    if len(output_text) > 8000:
        ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        temp_file = os.path.join(TEMP_DIR, f"resultado_agy_{ts}.md")
        try:
            with open(temp_file, "w", encoding="utf-8") as f:
                f.write(output_text)
            generated_files.append(temp_file)
            preview = output_text[:600].strip()
            output_text = (
                f"📄 <b>Resultado Extenso Generado ({len(output_text)} caracteres)</b>\n\n"
                f"{preview}...\n\n"
                f"📎 <i>El documento completo ha sido adjuntado en formato Markdown.</i>"
            )
        except Exception as e:
            logger.warning(f"No se pudo guardar archivo temporal extenso: {e}")

    if return_dict:
        return {"text": output_text, "files": generated_files}
    return output_text
