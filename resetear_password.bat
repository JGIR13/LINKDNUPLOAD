@echo off
cd /d "%~dp0"

if exist ".venv\Scripts\activate.bat" goto :venv_ok
echo [ERROR] No encuentro el entorno virtual .venv
echo Ejecuta primero setup_entorno.bat
pause
exit /b 1

:venv_ok
call ".venv\Scripts\activate.bat"

set /p CORREO="Email de la cuenta a resetear: "
python resetear_password.py "%CORREO%"

pause
