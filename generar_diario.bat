@echo off
cd /d "%~dp0"

if exist ".venv\Scripts\activate.bat" goto :venv_ok
echo [ERROR] No encuentro el entorno virtual .venv
echo Ejecuta primero setup_entorno.bat
exit /b 1

:venv_ok
if exist ".env" goto :env_ok
echo [ERROR] No encuentro el archivo .env en esta carpeta.
echo Ejecuta primero setup_entorno.bat
exit /b 1

:env_ok
call ".venv\Scripts\activate.bat"

echo [generar_diario] Ejecutando generacion diaria (Automatizacion Total)...
python generar_diario.py
set EXIT_CODE=%ERRORLEVEL%

echo [generar_diario] Terminado con codigo %EXIT_CODE%.
exit /b %EXIT_CODE%
