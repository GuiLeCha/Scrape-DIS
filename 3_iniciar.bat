@echo off
chcp 65001 >nul
title Scrape-DIS (AWS Academy Extractor & Content Player)

echo ============================================================
echo      Iniciando Scrape-DIS (AWS Academy Extractor)
echo ============================================================
echo.

:: Verificar si existe el entorno virtual
if not exist "venv\Scripts\activate.bat" (
    echo [ERROR] No se encontró el entorno virtual 'venv'.
    echo Por favor ejecutá primero el paso 1 haciendo doble clic en:
    echo    "1_instalar.bat"
    echo.
    pause
    exit /b 1
)

:: Verificar si existe el archivo .env
if not exist ".env" (
    echo [ADVERTENCIA] No se encontró el archivo .env.
    echo Creando uno por defecto desde .env.example...
    copy .env.example .env >nul
    echo Se recomienda revisar tus credenciales ejecutando "2_configurar.bat".
    echo.
)

:: Activar entorno virtual y lanzar programa
call venv\Scripts\activate.bat
python aws_academy_extractor.py

if %errorlevel% neq 0 (
    echo.
    echo El programa finalizó con una observación o fue cancelado.
)

echo.
pause
