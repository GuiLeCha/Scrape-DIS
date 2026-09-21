@echo off
chcp 65001 >nul
title Scrape-DIS - Paso 1: Instalación de Dependencias

echo ============================================================
echo           Scrape-DIS - Instalador Automático
echo ============================================================
echo.

:: 1. Verificar si Python está instalado
python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo [ERROR] No se detectó Python en tu sistema.
    echo Por favor descargá e instalá Python 3.10 o superior desde:
    echo https://www.python.org/downloads/
    echo.
    echo IMPORTANTE: Marcá la casilla "Add python.exe to PATH" durante la instalación.
    echo.
    pause
    exit /b 1
)

echo [1/4] Verificando Python...
python --version
echo.

:: 2. Crear entorno virtual si no existe
if not exist "venv" (
    echo [2/4] Creando entorno virtual aislado (venv)...
    python -m venv venv
    if %errorlevel% neq 0 (
        echo [ERROR] Falló la creación del entorno virtual.
        pause
        exit /b 1
    )
) else (
    echo [2/4] El entorno virtual ya existe. Continuando...
)
echo.

:: 3. Activar entorno virtual e instalar requerimientos
echo [3/4] Instalando librerías de Python desde requirements.txt...
call venv\Scripts\activate.bat
python -m pip install --upgrade pip >nul 2>&1
pip install -r requirements.txt
if %errorlevel% neq 0 (
    echo [ERROR] Ocurrió un error al instalar las librerías.
    pause
    exit /b 1
)
echo.

:: 4. Instalar navegador Chromium para Playwright
echo [4/4] Instalando navegadores para Playwright (Chromium)...
playwright install chromium
if %errorlevel% neq 0 (
    echo [AVISO] Ocurrió un detalle al instalar Chromium, pero intentaremos continuar.
)
echo.

:: 5. Verificar FFmpeg
where ffmpeg >nul 2>&1
if %errorlevel% neq 0 (
    echo ------------------------------------------------------------
    echo [AVISO SOBRE FFMPEG]:
    echo FFmpeg no fue detectado en el PATH de Windows.
    echo Es necesario para descargar videos y quemar subtítulos.
    echo.
    echo Si tenés Windows 10/11 podés instalarlo fácilmente abriendo
    echo otra consola y ejecutando: winget install Gyan.FFmpeg
    echo O descargarlo desde: https://www.gyan.dev/ffmpeg/builds/
    echo ------------------------------------------------------------
    echo.
)

echo ============================================================
echo       ¡INSTALACIÓN COMPLETADA EXITOSAMENTE!
echo ============================================================
echo.
echo Ahora ejecutá el paso 2 haciendo doble clic en:
echo    "2_configurar.bat"
echo.
pause
