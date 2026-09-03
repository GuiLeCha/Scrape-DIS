# AWS Academy Material Extractor (v3.7)

Extractor automatizado y asistente de estudio para materiales de **AWS Academy (Canvas LMS)**.

Permite descargar y consolidar automáticamente todo el contenido de los módulos de un curso de AWS Academy en formatos locales listos para estudiar (`.pdf`, `.mp4` y `.txt`), con soporte para quemado de subtítulos en español y sincronización opcional con Google Drive.

---

## 🚀 Características Principales

- **Detección y Extracción Multi-Formato**:
  - **Páginas Canvas (HTML)**: Convierte el texto y diagramas a `.pdf` con inyección de imágenes embebidas en Base64.
  - **Videos (MP4)**: Descarga el video, recupera pistas de subtítulos en español (VTT o cues de Video.js), quema los subtítulos directamente en el video con FFmpeg (x264, 720p optimizado) y guarda la transcripción en `.txt`.
  - **PDFs protegidos**: Descarga directa del binario original o reconstrucción página por página a través del visor Canvas.
- **Exploración Automatizada de Canvas**:
  - Listado automático de módulos disponibles mediante un menú desplegable en la interfaz.
  - Filtrado inteligente de evaluaciones, cuestionarios (*quizzes*) e ítems calificables online.
- **Reanudación Atómica (Checkpoints)**:
  - Guarda el progreso mediante identificadores SHA-256 por módulo. Si una descarga se interrumpe, se reanuda automáticamente sin re-descargar archivos ya completados y válidos.
- **Sincronización Opcional con Google Drive**:
  - Sube o actualiza automáticamente los materiales extraídos en carpetas organizadas por módulo en tu unidad de Google Drive.
- **Interfaz Gráfica Optimizada**:
  - Construida en Tkinter con soporte nativo de escalado DPI para pantallas de alta resolución en Windows.
  - Botón de cancelación inmediata (`⏹ Detener`), barra de progreso en vivo para FFmpeg y visor de log con límite de búfer.

---

## 📦 Requisitos Previos

1. **Python 3.10 o superior**.
2. **FFmpeg**: Necesario para el procesamiento y quemado de subtítulos de video. Debe estar agregado al PATH o configurado en `FFMPEG_PATH`.
3. **Google Chrome / Chromium**: Gestionado automáticamente por Playwright.

---

## 🛠 Instalación

1. Clona este repositorio:
   ```bash
   git clone https://github.com/GuiLeCha/Scraper-AWS.git
   cd Scraper-AWS
   ```

2. Instala las dependencias de Python:
   ```bash
   pip install -r requirements.txt
   ```

3. Instala los navegadores necesarios para Playwright:
   ```bash
   playwright install chromium
   ```

4. Configura el archivo de variables de entorno:
   ```bash
   cp .env.example .env
   ```
   Edita `.env` con la URL de tu curso en AWS Academy y las rutas deseadas.

---

## 💻 Uso

Ejecuta el programa principal:

```bash
python main.py
```

O utilizando el wrapper de compatibilidad:

```bash
python aws_academy_extractor_v3_6.py
```

### Flujo de trabajo:
1. Pulsa **«🌐 1. Iniciar sesión AWS»** para autenticarte en AWS Academy con tu cuenta y guardar la sesión persistente.
2. Pulsa **«🔄 Listar módulos»** para cargar los módulos del curso en el desplegable, o escribe directamente el nombre del módulo.
3. Pulsa **«⇩ 2. Descargar módulo»** para iniciar la extracción automatizada.

---

## 📁 Estructura del Proyecto

```text
├── main.py                         # Punto de entrada principal
├── aws_academy_extractor_v3_6.py   # Wrapper de compatibilidad
├── requirements.txt                # Dependencias del proyecto
├── .env.example                    # Plantilla de configuración
├── aws_extractor/                  # Paquete modular
│   ├── config.py                   # Ajustes y carga de variables de entorno
│   ├── utils.py                    # Sanitización, DPI en Windows y utilidades
│   ├── core/
│   │   ├── checkpoint.py           # Gestión atómica de estados y validación
│   │   ├── discovery.py            # Detección y filtrado en Canvas LMS
│   │   ├── drive.py                # Sincronización con Google Drive (OAuth2)
│   │   └── extractor.py            # Orquestador del flujo y Playwright
│   ├── extractors/
│   │   ├── base.py                 # Descarga de recursos HTTP
│   │   ├── html_pdf.py             # Conversión HTML Canvas a PDF
│   │   ├── viewer_pdf.py           # Captura y ensamblado de PDFs
│   │   └── video.py                # Detección y extracción de videos
│   ├── media/
│   │   ├── ffmpeg.py               # Transcodificación y progreso de FFmpeg
│   │   └── subtitles.py            # Heurísticas de subtítulos y formato VTT
│   └── ui/
│       └── app.py                  # Interfaz gráfica Tkinter
```

---

## 🔒 Privacidad y Credenciales

- Este repositorio **no almacena** tokens de acceso, perfiles de sesión ni contraseñas.
- Si utilizas la integración con Google Drive, coloca tus credenciales OAuth en la carpeta local `private/credentials_drive.json` (ignorada por `.gitignore`).
