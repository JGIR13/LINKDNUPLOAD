@echo off
cd /d "%~dp0"

if exist ".venv\Scripts\activate.bat" goto :venv_ok
echo [ERROR] No encuentro el entorno virtual .venv
echo Ejecuta primero setup_entorno.bat
pause
exit /b 1

:venv_ok
if exist ".env" goto :env_ok
echo [ERROR] No encuentro el archivo .env en esta carpeta.
echo Ejecuta primero setup_entorno.bat
echo.
echo ---- Contenido actual de esta carpeta (incluye ocultos) ----
dir /a /b
echo --------------------------------------------------------------
pause
exit /b 1

:env_ok
call ".venv\Scripts\activate.bat"

echo Iniciando LinkedIn AI Poster en http://localhost:8501 ...
echo Deja esta ventana abierta mientras uses la app. Cierrala para detenerla.
echo.

streamlit run app.py

pause
