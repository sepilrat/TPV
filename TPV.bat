@echo off
REM ============================================================
REM  TPV Autoservicio — doble clic y listo.
REM
REM  Abre el sistema contra la base REAL del negocio.
REM  Para probar cosas sin riesgo, usa TPV_MODO_PRUEBA.bat.
REM ============================================================

cd /d "%~dp0"
title TPV Autoservicio

REM pythonw.exe abre sin ventana negra detras. Si no esta, se usa
REM python.exe, que funciona igual pero deja la consola abierta.
set PY=.venv\Scripts\pythonw.exe
if not exist "%PY%" set PY=.venv\Scripts\python.exe
if not exist "%PY%" set PY=pythonw
if not exist "main.py" (
    echo.
    echo   No encuentro main.py en esta carpeta.
    echo   El acceso directo tiene que apuntar a la carpeta del TPV.
    echo.
    pause
    exit /b 1
)

REM El arranque queda registrado: con pythonw no hay ventana donde
REM leer un error, y sin esto un fallo al iniciar es invisible.
start "" "%PY%" main.py

REM Se espera un momento y se revisa que siga vivo. Si murio al toque,
REM se reintenta con python.exe para poder VER el error.
timeout /t 3 /nobreak >nul
tasklist /fi "imagename eq pythonw.exe" 2>nul | find /i "pythonw.exe" >nul
if errorlevel 1 (
    echo.
    echo   El TPV no arranco. Se reintenta mostrando el error...
    echo.
    set PYERR=.venv\Scripts\python.exe
    if not exist "%PYERR%" set PYERR=python
    "%PYERR%" main.py
    echo.
    pause
)
