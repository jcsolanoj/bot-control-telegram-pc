# 🚀 Manual de Instalación y Despliegue: Asistente Antigravity para Telegram

Este paquete te permite convertir tu computadora personal en un **servidor de inteligencia artificial autónomo y privado** conectado 24/7 a tu cuenta de Telegram.

---

## 📋 Requisitos Previos

Antes de comenzar, asegúrate de tener:

1. **Python 3.10 o superior** instalado en Windows:
   * Descárgalo de [python.org/downloads](https://www.python.org/downloads/).
   * ⚠️ **MUY IMPORTANTE:** Al instalar, marca la casilla que dice **"Add python.exe to PATH"**.
2. **Google Chrome** instalado (para navegación web automatizada).
3. **Antigravity CLI (`agy.exe`)** (Opcional pero muy recomendado para programación autónoma y gestión de proyectos):
   * Verifica su instalación abriendo PowerShell y ejecutando `agy --version`.
   * Inicia sesión con tu cuenta de Google ejecutando `agy` una vez para autenticarte.
4. Una cuenta de **Telegram**.
5. Una clave gratuita de **Google Gemini API** (para transcripción de notas de voz en alta velocidad).

---

## 🔑 Paso 1: Obtener las Claves Necesarias

### A. Token de tu Bot de Telegram
1. Abre Telegram y busca al bot oficial: **`@BotFather`**.
2. Escríbele `/newbot`.
3. Sigue las instrucciones: te pedirá un nombre para tu bot (ej. *Mi Asistente IA*) y un usuario que termine en `bot` (ej. *mi_asistente_personal_bot*).
4. BotFather te dará un **Token HTTP API** (se ve así: `1234567890:ABCdefGhIJKlmNoPQRsTUVwxyZ`). **Guarda este token.**

### B. Tu ID Numérico de Telegram (Seguridad)
Por seguridad estricta, tu asistente **solo te obedecerá a ti** y rechazará cualquier mensaje de desconocidos.
1. Abre Telegram y busca al bot: **`@userinfobot`**.
2. Envíale un mensaje (por ejemplo *"hola"*).
3. Te responderá con tu **Id** (un número como `123456789`). **Guarda este número.**

### C. Clave API de Google Gemini (Gratuita)
1. Entra con tu cuenta de Google a: [aistudio.google.com/app/apikey](https://aistudio.google.com/app/apikey).
2. Haz clic en **"Create API Key"** (Crear clave de API).
3. Copia la clave generada (empieza por `AIza...` o `AQ...`).

---

## ⚡ Paso 2: Instalación y Configuración en 1 Clic

Dentro de esta carpeta encontrarás los scripts numerados en orden:

### 1️⃣ Ejecutar `1_INSTALAR_DEPENDENCIAS.bat`
* Haz doble clic en este archivo.
* Se encargará automáticamente de actualizar `pip`, instalar todas las librerías necesarias (`python-telegram-bot`, `google-genai`, `playwright`, `psutil`, etc.) e instalar el motor de Chromium.

### 2️⃣ Ejecutar `2_CONFIGURAR_BOT.bat`
* Haz doble clic en este archivo.
* Se abrirá un asistente interactivo en la consola que te pedirá:
  1. Tu Token de Telegram.
  2. Tu ID numérico de Telegram.
  3. Tu clave de Google Gemini API.
* Al finalizar, creará automáticamente el archivo de configuración seguro `core\.env`.

### 3️⃣ Probar en modo visible: `3_INICIAR_BOT_VISIBLE.bat`
* Haz doble clic para arrancar el bot en una ventana de consola.
* Abre Telegram en tu móvil y saluda a tu bot escribiéndole *"Hola"* o mándale un audio.
* Verás en la consola cómo procesa tu petición y te responde de inmediato.

---

## 🛡️ Paso 3: Ponerlo en Modo Invisible y Auto-Arranque

Una vez verificado que responde correctamente:

1. **Cerrar la consola visible:** Presiona `Ctrl + C` en la ventana negra o ciérrala.
2. **Iniciar 100% en segundo plano:**
   * Haz doble clic en **`4_INICIAR_EN_SEGUNDO_PLANO.vbs`**.
   * El bot arrancará de forma totalmente invisible, sin ventanas en tu pantalla ni en la barra de tareas.
3. **Activar para que arranque solo al encender la PC:**
   * Haz doble clic en **`5_ACTIVAR_INICIO_AUTOMATICO.bat`**.
   * Creará automáticamente el acceso directo en tu carpeta de inicio de Windows. A partir de ahora, cada vez que enciendas tu PC, el asistente estará listo esperando tus órdenes.

---

## 🛑 Cómo detener el Asistente
Si necesitas apagar el bot o hacer mantenimiento:
* Haz doble clic en **`DETENER_BOT.bat`**.
* Finalizará inmediatamente cualquier proceso del asistente que esté en ejecución.

---

## 💡 Capacidades Principales Disponibles desde Telegram

* **🚀 Antigravity CLI Autónomo (`agy.exe`):** Escribe código, refactoriza proyectos, depura scripts y procesa datos complejos con memoria persistente.
* **📌 Gestión de Proyectos (`/proyecto`):**
  * `/proyecto`: Lista el proyecto activo y los proyectos registrados.
  * `/proyecto <nombre>`: Fija el proyecto de trabajo (ej. `/proyecto mi_app`).
  * `/proyecto libre`: Vuelve al modo libre general (`NO PROJECT`).
* **🛑 Cancelación Inmediata (`/cancelar` o `/stop`):** Aborta al instante cualquier proceso activo sin dejar procesos huérfanos.
* **📁 Búsqueda y entrega de archivos:** *"Búscame el contrato de arrendamiento en PDF y envíamelo aquí"*.
* **🌐 Navegación web con capturas:** *"Entra a wikipedia.org y resúmeme el artículo del día"* (te responderá con el texto y una captura de pantalla adjunta).
* **💻 Control de la PC:**
  * *"¿Cómo está mi computadora?"* (te dice CPU, RAM, batería y disco).
  * *"Bloquea la PC"* (protege tu pantalla manteniendo el bot activo).
  * *"Apaga la PC en 5 minutos"* / *"Cancela el apagado"*.
* **🎙️ Notas de voz:** Puedes hablarle con audios de Telegram con total libertad.
* **🖥️ Panel de Control de Escritorio:** En `core/control_panel.py` tienes un panel visual para Encender, Apagar y Comprobar el estado del bot en 1 clic.
