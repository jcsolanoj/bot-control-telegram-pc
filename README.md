# bot-control-telegram-pc

Asistente remoto para **Windows 10/11** que conecta un bot privado de **Telegram** con **Google Gemini** (`google-genai`), **Playwright** y control del sistema local. Permite ejecutar tareas desde el móvil mediante texto o notas de voz: buscar y recibir archivos, navegar sitios web con capturas, monitorear hardware, capturar pantalla, gestionar proyectos locales y controlar energía de la PC.

> 📘 Para una guía detallada paso a paso, consulta [MANUAL_PASO_A_PASO.md](MANUAL_PASO_A_PASO.md).

---

## Requisitos previos

- **Windows 10 / 11** con **Python 3.10+** (*Add python.exe to PATH* marcado).
- **Google Chrome** instalado (usado por Playwright para sesiones persistentes).
- Cuenta de **Telegram** (Token de `@BotFather` + tu User ID de `@userinfobot`).
- Clave de **Google Gemini API** ([Google AI Studio](https://aistudio.google.com/apikey)).
- *(Opcional)* **Antigravity CLI (`agy.exe`)** para delegación avanzada de proyectos con `/proyecto`.

---

## Instalación rápida

1. Clona el repositorio:
   ```bash
   git clone https://github.com/jcsolanoj/bot-control-telegram-pc.git
   cd bot-control-telegram-pc
   ```
2. Instala las dependencias ejecutando `1_INSTALAR_DEPENDENCIAS.bat` (o manualmente `pip install -r core/requirements.txt` y `playwright install chromium`).
3. Configura tus credenciales copiando `core/.env.example` a `core/.env` (o ejecutando `2_CONFIGURAR_BOT.bat`).
4. Inicia el bot:
   - Modo visible (para pruebas/diagnóstico): `3_INICIAR_BOT_VISIBLE.bat`
   - Modo segundo plano: `4_INICIAR_EN_SEGUNDO_PLANO.vbs`
   - Panel gráfico de estado: `python core/control_panel.py`
   - Detener el bot: `DETENER_BOT.bat`

---

## Seguridad y buenas prácticas

- **Control de acceso estricto (Fail-Closed):** El bot valida al arrancar `TELEGRAM_BOT_TOKEN`, `GEMINI_API_KEY` y `TELEGRAM_ALLOWED_USER_ID`, y solo responde en **chat privado** al usuario autorizado.
- **Protección de secretos:** `core/.env`, `core/user_profile.json`, `core/chat_history.json` y `core/project_sessions.json` están excluidos en `.gitignore` y bloqueados en la herramienta de adjuntos a Telegram.
- **Logs y diagnóstico:** Si el bot corre en segundo plano, revisa `core/bot.log`, `core/bot_stderr.log` o `core/crash.log`.

---

## Pruebas

```bash
pytest -v
```

---

## Licencia

Distribuido bajo licencia MIT. Consulta [LICENSE](LICENSE) para más detalles.
