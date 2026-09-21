@echo off
chcp 65001 >nul
title Scrape-DIS - Paso 2: Configuración del Entorno (.env)

echo ============================================================
echo          Scrape-DIS - Configuración del Entorno
echo ============================================================
echo.

if not exist ".env" (
    echo [INFO] Creando archivo .env a partir de .env.example...
    copy .env.example .env >nul
    echo [OK] Archivo .env creado con éxito.
) else (
    echo [INFO] Ya existe un archivo .env configurado.
)

echo.
echo ============================================================
echo A continuación se abrirá el archivo .env en el Bloc de Notas.
echo.
echo Por favor revisá o completá los siguientes datos:
echo   1. AWS_USER: Tu correo o usuario de AWS Academy / Canvas.
echo   2. AWS_PASSWORD: Tu contraseña de acceso.
echo   3. AWS_HOME_URL: La URL de tu curso (por defecto el curso 183094 de IFTS29).
echo.
echo Al terminar:
echo   - Guardá los cambios con [Ctrl + G] o Archivo -^> Guardar.
echo   - Cerrá el Bloc de Notas.
echo ============================================================
echo.
pause

notepad.exe .env

echo.
echo ============================================================
echo       ¡CONFIGURACIÓN COMPLETADA!
echo ============================================================
echo.
echo Ahora podés arrancar el programa haciendo doble clic en:
echo    "3_iniciar.bat"
echo.
pause
