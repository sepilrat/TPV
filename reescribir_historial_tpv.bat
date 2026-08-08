@echo off
setlocal enabledelayedexpansion
echo ================================================================
echo   Reescritura de historial del repo TPV
echo   ATENCION: esto reescribe TODOS los commits (nuevos hashes).
echo   Vas a necesitar hacer push forzado al final.
echo   Si tenes el repo clonado en otra PC, ahi hay que reclonarlo.
echo ================================================================
echo.
set /p CONFIRMA="Escribi SI para continuar: "
if /i not "%CONFIRMA%"=="SI" (
    echo Cancelado.
    pause
    exit /b 0
)

cd /d "C:\Users\juampa\Dropbox\Sistemas\TPV"
if errorlevel 1 (
    echo ERROR: no se encontro la carpeta del proyecto.
    pause
    exit /b 1
)

if not exist ".git" (
    echo ERROR: esta carpeta no tiene un repo .git inicializado.
    pause
    exit /b 1
)

echo.
echo Guardando la URL del remoto...
for /f "tokens=*" %%i in ('git remote get-url origin') do set REMOTE_URL=%%i
echo Remoto actual: %REMOTE_URL%

echo.
echo [1/4] Instalando git-filter-repo si hace falta...

set PYCMD=
where python >nul 2>&1
if not errorlevel 1 set PYCMD=python
if "%PYCMD%"=="" (
    where py >nul 2>&1
    if not errorlevel 1 set PYCMD=py
)
if "%PYCMD%"=="" (
    echo ERROR: no se encontro python en el PATH. Instala Python desde python.org
    echo o reparalo, y volve a correr este script.
    pause
    exit /b 1
)
echo Usando: %PYCMD%

%PYCMD% -m pip --version >nul 2>&1
if errorlevel 1 (
    echo pip no esta disponible, intentando repararlo con ensurepip...
    %PYCMD% -m ensurepip --upgrade
    if errorlevel 1 (
        echo ERROR: no se pudo reparar pip automaticamente.
        echo Instala pip manualmente ^(por ejemplo descargando get-pip.py^) y volve a correr este script.
        pause
        exit /b 1
    )
)

%PYCMD% -m pip install git-filter-repo -q
if errorlevel 1 (
    echo ERROR: no se pudo instalar git-filter-repo con pip.
    pause
    exit /b 1
)

echo.
echo [2/4] Reescribiendo historial (puede tardar unos segundos)...
%PYCMD% -m git_filter_repo --force ^
  --path .venv --path __pycache__ --path backups --path logs ^
  --path tpv2.db --path tpv2.db-wal --path tpv2.db-shm ^
  --path files.zip --path test_conexion_openfoodfacts.py --path .vscode ^
  --invert-paths

if errorlevel 1 (
    echo ERROR durante filter-repo. No se hizo push, tu backup local del repo sigue intacto.
    pause
    exit /b 1
)

echo.
echo [3/4] Restaurando el remoto (filter-repo lo saca por seguridad)...
git remote add origin %REMOTE_URL%

echo.
echo [4/4] Haciendo push forzado...
git push --force --set-upstream origin main

echo.
echo ================================================================
echo   Listo. Repo reescrito y subido.
echo   Tamano nuevo de .git:
for /f "usebackq" %%s in (`powershell -command "'{0:N1} MB' -f ((Get-ChildItem .git -Recurse | Measure-Object -Property Length -Sum).Sum / 1MB)"`) do echo   %%s
echo ================================================================
pause
