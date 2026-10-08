@echo off
cd /d "%~dp0"

echo ============================================
echo  LinkedIn AI Poster - Preparar entorno
echo ============================================
echo.

rem --- Detectar Python: primero "python", si no "py" (lanzador de Windows) ---
set "PY="
python --version >nul 2>nul && set "PY=python"
if not defined PY py --version >nul 2>nul && set "PY=py"
if not defined PY goto :no_python
echo Usando: %PY%

if exist ".venv\Scripts\activate.bat" goto :venv_ok
echo Creando entorno virtual en .venv ...
%PY% -m venv .venv
if errorlevel 1 goto :venv_fallo
goto :venv_listo

:venv_ok
echo El entorno virtual .venv ya existe, lo reutilizo.

:venv_listo
call ".venv\Scripts\activate.bat"

echo.
echo Instalando dependencias de requirements.txt ...
python -m pip install --upgrade pip >nul
pip install -r requirements.txt

echo.
if exist ".env" goto :env_existente

echo No existe .env todavia. Lo voy a crear ahora.
echo.
echo Para generar texto e imagenes necesitas una clave de Gemini (gratis).
echo Consiguela en: https://aistudio.google.com/apikey
echo.
set "GEMINI_KEY_INPUT="
set /p GEMINI_KEY_INPUT="Pega aqui tu GEMINI_API_KEY y pulsa Enter (o deja vacio y la rellenas despues): "

echo MODO_CLAVES=propio> ".env"
echo GEMINI_API_KEY=%GEMINI_KEY_INPUT%>> ".env"
echo LINKEDIN_CLIENT_ID=>> ".env"
echo LINKEDIN_CLIENT_SECRET=>> ".env"
echo LINKEDIN_REDIRECT_URI=http://localhost:8501>> ".env"

if not exist ".env" goto :env_fallo

echo.
echo .env creado.
if "%GEMINI_KEY_INPUT%"=="" goto :env_revisar_clave
echo Tu GEMINI_API_KEY ha quedado guardada. Ya puedes usar iniciar_app.bat.
echo Si en el futuro quieres publicar en LinkedIn, rellena tambien
echo LINKEDIN_CLIENT_ID y LINKEDIN_CLIENT_SECRET en .env - ver el README.
goto :listado

:env_fallo
echo [ERROR] No se pudo crear .env. Revisa que esta carpeta no sea de solo lectura.
goto :listado

:env_existente
echo Ya existe un .env en esta carpeta.
findstr /b /r /c:"GEMINI_API_KEY=." ".env" >nul
if not errorlevel 1 goto :env_clave_ok

:env_revisar_clave
echo.
echo [AVISO IMPORTANTE] Tu .env NO tiene la GEMINI_API_KEY rellenada.
echo Esto es justo lo que causa el error "No hay GEMINI_API_KEY configurada"
echo al generar un post. Sin ella la app no puede llamar a Gemini.
echo.
echo Voy a abrir .env con el Bloc de notas. Pega tu clave despues del signo
echo "=" en la linea GEMINI_API_KEY= (consiguela gratis en
echo https://aistudio.google.com/apikey si no la tienes). Guarda con Ctrl+S
echo y cierra el Bloc de notas para continuar.
echo.
pause
start "" /wait notepad ".env"
echo.
echo Continuando... (si no la rellenaste, la app te lo seguira avisando).
goto :listado

:env_clave_ok
echo Tu .env ya tiene una GEMINI_API_KEY rellenada - no hace falta tocar nada.

:listado
echo.
echo ---- Contenido actual de esta carpeta (incluye ocultos) ----
dir /a /b
echo --------------------------------------------------------------

echo.
echo ============================================
echo  Listo. Ya puedes usar iniciar_app.bat
echo ============================================
pause
goto :eof

:venv_fallo
echo [ERROR] No se pudo crear el entorno virtual con "%PY%".
pause
exit /b 1

:no_python
echo [ERROR] No se encontro Python (ni "python" ni "py").
echo Instala Python desde https://www.python.org/downloads/
echo y marca la casilla "Add python.exe to PATH" durante la instalacion.
pause
exit /b 1
