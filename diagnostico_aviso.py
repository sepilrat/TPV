"""
diagnostico_aviso.py — Por qué no llega el mail automático.

Revisa la configuración, las marcas del día y hace un envío de prueba,
diciendo en cada paso qué falta.

USO
---
    .venv\\Scripts\\python.exe diagnostico_aviso.py

Con --enviar hace además un envío real forzado, para ver si el problema
es la programación o el correo en sí:

    .venv\\Scripts\\python.exe diagnostico_aviso.py --enviar
"""

import sys
from datetime import datetime

from config import cfg


def _ok(txt):
    print(f"   [OK]    {txt}")


def _mal(txt):
    print(f"   [FALTA] {txt}")
    return False


def main():
    c = cfg()
    print("=" * 68)
    print("DIAGNÓSTICO DEL AVISO DIARIO")
    print("=" * 68)
    todo_bien = True

    print("\n1. CONFIGURACIÓN DEL CORREO")
    if not c.get("email_activo"):
        todo_bien = _mal("«Email» está desactivado (Config → Email SMTP)")
    else:
        _ok("Email activo")
    for clave, etq in (("email_usuario", "Usuario SMTP"),
                       ("email_password", "Contraseña SMTP"),
                       ("email_smtp_host", "Servidor SMTP")):
        if not c.get(clave):
            todo_bien = _mal(f"Falta {etq}")
        else:
            _ok(f"{etq} cargado")

    print("\n2. CONFIGURACIÓN DEL AVISO")
    if not c.get("aviso_diario_activo"):
        todo_bien = _mal("«Activar el aviso diario» está en NO")
    else:
        _ok("Aviso diario activo")

    dest = (c.get("aviso_diario_destinatario") or "").strip()
    if not dest:
        todo_bien = _mal("No hay destinatario cargado")
    else:
        _ok(f"Destinatario: {dest}")

    print("\n3. ¿QUÉ DISPARADORES ESTÁN PRENDIDOS?")
    disp = [
        ("aviso_diario_a_las", "a una hora fija"),
        ("aviso_diario_al_abrir_app", "al abrir el sistema"),
        ("aviso_diario_al_abrir_caja", "al abrir la caja"),
        ("aviso_diario_al_cerrar_caja", "al cerrar la caja"),
    ]
    prendidos = [e for k, e in disp if c.get(k)]
    for k, etq in disp:
        print(f"   {'[SÍ]' if c.get(k) else '[no]'}  {etq}")
    if not prendidos:
        todo_bien = _mal("Ningún disparador prendido: el aviso no sale nunca")
    elif len(prendidos) > 1:
        print(f"\n   Ojo: {len(prendidos)} disparadores prendidos = "
              f"{len(prendidos)} mails por día.")

    if c.get("aviso_diario_a_las"):
        hora = c.get("aviso_diario_hora", 21)
        try:
            hora = int(str(hora).split(":")[0])
        except (ValueError, IndexError):
            hora = 21
        ahora = datetime.now()
        print(f"\n   Hora configurada: {hora:02d}:00   ·   ahora son las "
              f"{ahora.strftime('%H:%M')}")
        if ahora.hour < hora:
            print(f"   Todavía no es la hora: sale a las {hora:02d}:00, "
                  f"con el TPV abierto.")
        else:
            print("   La hora ya pasó: debería haber salido hoy.")

    print("\n4. MARCAS DE ENVÍO DE HOY")
    hoy = datetime.now().strftime("%Y-%m-%d")
    marcas = {k: v for k, v in c.items()
              if k.startswith("_aviso_diario_ultimo_envio")}
    if not marcas:
        print("   Ninguna: nunca se envió.")
    for k, v in sorted(marcas.items()):
        motivo = k.replace("_aviso_diario_ultimo_envio_", "") or "(sin motivo)"
        if v == hoy:
            print(f"   {motivo:<28} ya se envió HOY")
        elif v:
            print(f"   {motivo:<28} último: {v}")
        else:
            print(f"   {motivo:<28} sin enviar")

    print("\n" + "=" * 68)
    if todo_bien:
        print("La configuración está completa.")
        if any(v == hoy for v in marcas.values()):
            print("\nEl aviso de hoy YA SE ENVIÓ según las marcas de arriba.")
            print("Si no te llegó, revisá la carpeta de spam.")
        print("\nRecordá: el envío por hora fija necesita el TPV ABIERTO")
        print("en ese momento. Si a esa hora la máquina está apagada,")
        print("el mail no sale — se manda al abrir el TPV la próxima vez.")
    else:
        print("Corregí lo que dice [FALTA] arriba, en Config.")

    if "--enviar" in sys.argv:
        print("\n" + "=" * 68)
        print("ENVÍO DE PRUEBA (forzado, no consume el del día)")
        print("=" * 68)
        try:
            from impresion import enviar_aviso_diario
            ok, msg = enviar_aviso_diario("PRUEBA MANUAL", forzar=True)
            print(f"\n   {'[OK]' if ok else '[FALLA]'}  {msg}")
            if ok:
                print("\n   El correo funciona: el problema es la")
                print("   programación, no el envío.")
        except Exception as exc:
            print(f"\n   [FALLA]  {type(exc).__name__}: {exc}")
            # La traza completa dice en QUE LINEA se rompe: sin eso el
            # mensaje solo no alcanza para saber que dato lo causa.
            import traceback
            print("\n   DETALLE (copiá estas líneas):")
            for l in traceback.format_exc().splitlines():
                print("   " + l)
    else:
        print("\nPara probar el envío de verdad:")
        print("    .venv\\Scripts\\python.exe diagnostico_aviso.py --enviar")
    print("=" * 68)


if __name__ == "__main__":
    main()
