<#
crear_tareas_programadas.ps1 - Crea en el Programador de tareas de Windows
las tareas que mandan por mail los informes del TPV.

Se usa UNA SOLA VEZ: desde el TPV (Config -> boton "Tareas de Windows"), con
doble clic en crear_tareas_programadas.bat, o desde PowerShell:
    .\crear_tareas_programadas.ps1

Opciones:
    -Informes todos            (por defecto) facturacion + stock + vencimientos
    -Informes facturacion      solo uno, o varios separados por coma
    -Probar                    ejecuta cada tarea apenas se crea

LA HORA SE TOMA DE LA CONFIG DEL TPV, no de la tarea. Cada tarea corre cada
10 minutos con --programado y el script mira la hora de envio que figura en
Config; pasada esa hora manda una vez por dia. Cambiar la hora en el TPV
alcanza: no hay que volver a crear nada en Windows. (Se manda con hasta 10
minutos de diferencia.)

Detalles:
  * Corre con TU usuario, solo si esta con la sesion abierta (no pide clave).
  * "Iniciar en" queda en la carpeta del TPV.
  * Si la PC estaba apagada, manda apenas prenda (el mismo dia).
  * Usa pythonw.exe para que no aparezca una ventana negra.
  * Si la tarea ya existia, la reemplaza.
#>
param(
    [string]$Informes = "todos",
    [switch]$Probar
)

$ErrorActionPreference = "Stop"
$carpeta = Split-Path -Parent $MyInvocation.MyCommand.Path

$py = Join-Path $carpeta ".venv\Scripts\pythonw.exe"
if (-not (Test-Path $py)) { $py = Join-Path $carpeta ".venv\Scripts\python.exe" }
if (-not (Test-Path $py)) {
    throw "No encuentro el Python del TPV en $carpeta\.venv\Scripts. Corre esto desde la carpeta del TPV."
}

# nombre -> tarea, script, clave "activo" de la config, argumentos
$todos = [ordered]@{
    "facturacion"  = @{ Tarea = "TPV - Facturacion";  Script = "informe_facturacion_email.py";   Activo = "informe_facturacion_activo"; HoraKey = "informe_facturacion_hora"; HoraDef = "21:30"; Extra = " --programado"; Repite = $true }
    "stock"        = @{ Tarea = "TPV - Poco stock";   Script = "informe_stock_email.py";         Activo = "informe_stock_email_activo"; HoraKey = "informe_stock_email_hora";   HoraDef = "08:00"; Extra = " --programado";               Repite = $true }
    "vencimientos" = @{ Tarea = "TPV - Vencimientos"; Script = "informe_vencimientos_email.py";  Activo = "vto_email_activo";           HoraKey = "vto_email_hora";             HoraDef = "08:30"; Extra = " --programado";               Repite = $true }
}

$cfg = $null
$cfgPath = Join-Path $carpeta "tpv_config.json"
if (Test-Path $cfgPath) {
    try { $cfg = Get-Content $cfgPath -Raw -Encoding UTF8 | ConvertFrom-Json } catch { $cfg = $null }
}

if ($Informes.Trim().ToLower() -eq "todos") { $pedidos = @($todos.Keys) }
else { $pedidos = @($Informes.Split(",") | ForEach-Object { $_.Trim().ToLower() } | Where-Object { $_ }) }

foreach ($p in $pedidos) {
    if (-not $todos.Contains($p)) { throw "No conozco el informe '$p'. Opciones: facturacion, stock, vencimientos, todos." }
}

foreach ($p in $pedidos) {
    $d = $todos[$p]
    $script = Join-Path $carpeta $d.Script
    if (-not (Test-Path $script)) { throw "Falta el archivo $($d.Script) en $carpeta" }

    $activo = $false
    if ($cfg -and $cfg.($d.Activo)) { $activo = $true }

    $argumentos = '"' + $script + '"' + $d.Extra
    $accion = New-ScheduledTaskAction -Execute $py -Argument $argumentos -WorkingDirectory $carpeta

    # Una corrida cada 10 minutos, todo el dia. El script decide si ya es la hora.
    $disp = New-ScheduledTaskTrigger -Daily -At "00:00"
    $rep  = New-ScheduledTaskTrigger -Once -At "00:00" -RepetitionInterval (New-TimeSpan -Minutes 10) -RepetitionDuration (New-TimeSpan -Hours 23 -Minutes 59)
    $disp.Repetition = $rep.Repetition
    $ajustes = New-ScheduledTaskSettingsSet -StartWhenAvailable -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -MultipleInstances IgnoreNew -ExecutionTimeLimit (New-TimeSpan -Minutes 9)
    $cuando = "cada 10 minutos (manda a la hora que figura en Config)"

    try {
        Register-ScheduledTask -TaskName $d.Tarea -Action $accion -Trigger $disp -Settings $ajustes `
            -Description "TPV: envia por mail el informe de $p" -Force | Out-Null
    }
    catch {
        Write-Host ("[ERROR] No se pudo crear la tarea '" + $d.Tarea + "': " + $_.Exception.Message)
        Write-Host "        Crearla a mano: instrucciones al principio del archivo $($d.Script)"
        continue
    }

    Write-Host ("[OK] Tarea '" + $d.Tarea + "' creada: " + $cuando)
    if (-not $activo) {
        Write-Host ("[AVISO] En Config, '" + $d.Activo + "' esta destildado: la tarea corre pero NO manda nada hasta que lo tildes.")
    }
    if ($Probar) {
        Start-ScheduledTask -TaskName $d.Tarea
        Write-Host "        Ejecutada ahora. Para el informe de facturacion la prueba real es:"
        Write-Host "        .venv\Scripts\python.exe informe_facturacion_email.py   (manda el de hoy ya mismo)"
    }
}

Write-Host ""
Write-Host "Listo. Para verificar:  .venv\Scripts\python.exe diagnostico_email.py"
