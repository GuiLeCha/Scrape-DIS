# Scrape-DIS (AWS Academy Extractor & Content Player)

Herramienta automatizada en Python para estudiantes y docentes de **AWS Academy** sobre la plataforma **Canvas LMS**. 

Permite interactuar con los cursos de dos formas:
1. **Descarga estructurada de módulos**: Extrae guías PDF completas, videos interactivos SCORM con subtítulos en español incrustados (vía FFmpeg) y lecturas HTML organizadas en carpetas por módulo.
2. **Reproducción online con ritmo humano**: Recorre el curso de forma interactiva en el navegador, detecta videos, activa subtítulos en español, respeta su duración completa, hojea documentos PDF página a página y avanza de sección mediante el botón nativo **«Next / Siguiente»** de Canvas, omitiendo automáticamente evaluaciones y cuestionarios.

---

## 📋 Requisitos Previos

Antes de comenzar, asegúrate de tener instalado en tu equipo:

1. **Python 3.10 o superior** (descárgalo desde [python.org](https://www.python.org/downloads/) asegurándote de marcar la casilla *"Add python.exe to PATH"*).
2. **Google Chrome** instalado en el sistema (Playwright lo utiliza directamente para interactuar con Canvas y los componentes SCORM).
3. **FFmpeg** (necesario únicamente si vas a descargar videos y quemar subtítulos):
   - Descarga FFmpeg desde [gyan.dev/ffmpeg/builds](https://www.gyan.dev/ffmpeg/builds/) (versión `ffmpeg-release-essentials.zip`).
   - Descomprímelo (por ejemplo en `C:\ffmpeg`) y agrega su subcarpeta `bin` al PATH de Windows, o configura la ruta exacta en el archivo `.env`.

---

## 🚀 Instalación Rápida

Sigue estos pasos en tu terminal (PowerShell o CMD):

### 1. Clonar el repositorio
```bash
git clone https://github.com/GuiLeCha/Scrape-DIS.git
cd Scrape-DIS
```

### 2. Crear y activar un entorno virtual
Recomendado para mantener las librerías aisladas:

**En Windows (PowerShell):**
```powershell
python -m venv venv
.\venv\Scripts\Activate.ps1
```
> *Nota: Si PowerShell te muestra un error sobre ejecución de scripts, ejecuta antes:*
> ```powershell
> Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
> ```

**En Windows (CMD):**
```cmd
python -m venv venv
venv\Scripts\activate.bat
```

### 3. Instalar dependencias de Python
```bash
pip install --upgrade pip
pip install -r requirements.txt
```

### 4. Instalar los binarios de Playwright
```bash
playwright install chromium
```

---

## ⚙️ Configuración (.env)

El proyecto incluye una plantilla de configuración llamada `.env.example`. Crea tu archivo `.env` a partir de ella:

**En Windows:**
```cmd
copy .env.example .env
```

Abre `.env` con cualquier editor de texto (Notepad, VS Code, etc.) y completa tus parámetros:

```ini
# ==============================================================================
# 1. ACCESO A AWS ACADEMY / CANVAS
# ==============================================================================
# Credenciales para inicio de sesión automático.
# Si las dejas en blanco, podrás iniciar sesión a mano en la ventana de Chrome.
AWS_USER=tu_usuario_o_correo@ejemplo.com
AWS_PASSWORD=tu_contraseña_aqui

# URL de la sección de módulos de tu curso
AWS_HOME_URL=https://awsacademy.instructure.com/courses/183094/modules

# ==============================================================================
# 2. RUTAS LOCALES
# ==============================================================================
# Carpeta donde se guardará el material descargado
OUTPUT_DIR=C:/Users/TuUsuario/Documents/AWS_Material

# Carpeta de perfil de Chrome (guarda tu sesión para no pedir login cada vez)
PROFILE_DIR=C:/Users/TuUsuario/.aws_academy_extractor_profile

# ==============================================================================
# 3. FFMPEG (DESCARGAS DE VIDEO)
# ==============================================================================
# Ruta al ejecutable de FFmpeg
FFMPEG_PATH=C:/ffmpeg/bin/ffmpeg.exe
BURN_SUBTITLES=true

# ==============================================================================
# 4. VELOCIDAD Y SIMULACIÓN HUMANA (REPRODUCCIÓN ONLINE)
# ==============================================================================
SIM_VIDEO_SPEED=1.0          # Velocidad de reproducción (1.0x = tiempo real)
SIM_PDF_PAGE_SECONDS=12      # Segundos que permanece en cada página del PDF
SIM_HTML_READING_SECONDS=10  # Segundos de lectura en páginas de texto
SIM_SCROLL_DELAY=0.8         # Intervalo entre desplazamientos de scroll
```

---

## 💻 Modos de Uso

Ejecuta el programa principal con:

```bash
python aws_academy_extractor.py
```

Se abrirá una interfaz interactiva en consola que listará todos los módulos disponibles en tu curso de Canvas:

```text
============================================================
              AWS Academy Material Extractor
============================================================

1. Módulo 1 - Cloud Concepts Overview
2. Módulo 2 - Cloud Economics and Billing
3. Módulo 3 - AWS Global Infrastructure Overview
...
```

Selecciona el número del módulo con el que deseas trabajar (o `T` para todos). A continuación, el programa te consultará qué acción deseas realizar:

### Opción 1: Descargar módulo
- Analiza todos los ítems del módulo seleccionado.
- **Videos**: Descarga streams interactivos SCORM/VideoJS, descarga subtítulos en español y los incrusta en el video resultante con FFmpeg.
- **Guías de estudio (PDF)**: Espera a que el visor renderice todas las páginas en alta resolución y genera el archivo PDF completo.
- **Páginas HTML**: Guarda el contenido y diagramas en formato web navegable sin conexión.
- **Reanudación inteligente**: Si cancelas o se corta la conexión, al volver a correr no descargará los archivos que ya estén completos.

### Opción 2: Reproducir contenido (Modo Humano Online)
Diseñado para recorrer el curso directamente dentro de Canvas sin saturar la red ni guardar archivos en disco:
- **Detección inteligente de componentes**: Aguarda dinámicamente hasta 35 segundos para que los iframes interactivos (SCORM, Video.js o PDFViewer) terminen de cargarse.
- **Videos online con subtítulos**: Localiza el reproductor, activa los subtítulos en español (`mode: showing`) y reproduce el video de principio a fin a velocidad normal.
- **Lectura de PDFs**: Detecta el visor Canvas PDF, cuenta la cantidad total de páginas (ej. 44 páginas de la *Student Guide*) y hace scroll suave página a página simulando la lectura de un estudiante.
- **Transición nativa con botón «Next»**: Al finalizar cada sección, busca y presiona el botón nativo **«Next / Siguiente»** del pie de página de Canvas para avanzar fluidamente a la siguiente lección.
- **Omisión de tareas y exámenes**: Detecta y salta automáticamente cuestionarios (`quizzes`), asignaciones (`assignments`) y laboratorios externos para que puedas realizarlos de forma manual.

---

## 🛠️ Preguntas Frecuentes y Solución de Problemas

#### 1. ¿Qué pasa si mi cuenta requiere Doble Factor de Autenticación (2FA / MFA)?
El navegador Chrome se abre de forma visible en pantalla. Si Canvas te solicita un código SMS o una app de autenticación, ingrésalo normalmente en la ventana. La sesión quedará guardada en la carpeta especificada en `PROFILE_DIR`, por lo que las siguientes ejecuciones entrarán directo sin volver a pedirte el código.

#### 2. Mensaje "Chrome ya se encuentra en ejecución o el perfil está bloqueado"
Si cerraste abruptamente el programa en una ejecución anterior, puede quedar un archivo `SingletonLock` en la carpeta `PROFILE_DIR`. El programa lo limpia automáticamente en cada inicio, pero si persiste, asegúrate de que no haya ventanas de Chrome abiertas en segundo plano o elimina manualmente el archivo `SingletonLock` dentro de `PROFILE_DIR`.

#### 3. Error `ffmpeg is not recognized` o `No se encontró FFmpeg`
Verifica que en tu archivo `.env` la variable `FFMPEG_PATH` apunte al archivo `ffmpeg.exe` existente en tu disco (utilizando barras normales `/`, por ejemplo: `C:/ffmpeg/bin/ffmpeg.exe`).

#### 4. Pausar o cancelar una tarea en ejecución
Puedes presionar `Ctrl + C` en la consola en cualquier momento. El programa cerrará el contexto del navegador de forma segura y liberará el perfil de usuario.

---

## 📁 Estructura del Código

```text
Scrape-DIS/
├── aws_academy_extractor.py      # Punto de entrada principal
├── requirements.txt              # Dependencias del proyecto
├── .env.example                  # Plantilla de configuración
├── README.md                     # Documentación general
└── aws_extractor/                # Paquete modular
    ├── config.py                 # Carga de variables de entorno y Settings
    ├── core/
    │   ├── discovery.py          # Detección y clasificación de ítems en Canvas
    │   ├── extractor.py          # Motor de descarga (PDF, Video, HTML)
    │   ├── login.py              # Gestión de inicio de sesión automático
    │   └── player.py             # Motor de simulación y reproducción humana
    ├── extractors/
    │   ├── html_extractor.py     # Extracción y limpieza de HTML
    │   ├── pdf_extractor.py      # Extracción de PDF desde visor Canvas
    │   └── video_extractor.py    # Descarga de video y subtítulos
    ├── media/
    │   ├── ffmpeg_runner.py      # Interfaz con FFmpeg para compresión y subtítulos
    │   └── pdf_builder.py        # Ensamblador de páginas PDF con Pillow
    └── ui/
        └── console.py            # Menús de consola interactivos
```

---

## 📄 Licencia
Proyecto desarrollado para fines educativos y de respaldo personal de material de estudio.
