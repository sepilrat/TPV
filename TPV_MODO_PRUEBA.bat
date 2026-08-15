@echo off
REM ============================================================
REM  TPV en MODO PRUEBA — doble clic y listo.
REM
REM  Abre el sistema contra una copia de la base (tpv2_prueba.db).
REM  Todo lo que se haga aca es descartable: ventas, ajustes,
REM  precios. La base real no se toca.
REM
REM  Si la copia no existe, la crea sola.
REM ============================================================

cd /d "%~dp0"
title TPV - MODO PRUEBA

set PY=.venv\Scripts\python.exe
if not exist "%PY%" set PY=python

if not exist "tpv2_prueba.db" (
    echo.
    echo   No existe la base de prueba. Se crea una copia de la real...
    echo.
    echo s| "%PY%" crear_base_prueba.py
    echo.
)

echo.
echo   ==========================================================
echo    Abriendo el TPV en MODO PRUEBA
echo.
echo    Base: tpv2_prueba.db   ^(NO es la del negocio^)
echo    Nada de lo que hagas aca afecta a las ventas reales.
echo   ==========================================================
echo.

set TPV_DB=tpv2_prueba.db
"%PY%" main.py

REM Si el TPV cerro por un error, la ventana queda abierta para
REM poder leerlo en vez de desaparecer de golpe.
if errorlevel 1 (
    echo.
    echo   El TPV se cerro con un error. Mira el detalle de arriba.
    pause
)
