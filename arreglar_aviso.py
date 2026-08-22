"""
arreglar_aviso.py — Deja el aviso diario en el modo de hora fija.

Había cuatro disparadores para lo mismo, y la guarda de "uno por día"
hacía que el primero se comiera a los demás: si a las 12:23 salía uno
al abrir el sistema, el de las 21 no llegaba nunca.

Esto apaga los disparadores por evento y deja solo el de hora fija.

USO
---
    .venv\\Scripts\\python.exe arreglar_aviso.py
"""

from config import cfg, set as cfg_set


def main():
    c = cfg()
    print("=" * 60)
    print("AVISO DIARIO — estado actual")
    print("=" * 60)
    for k, etq in (("aviso_diario_activo",        "Activo"),
                   ("aviso_diario_destinatario",  "Destinatario"),
                   ("aviso_diario_a_las",         "A hora fija"),
                   ("aviso_diario_hora",          "Hora"),
                   ("aviso_diario_al_abrir_app",  "Al abrir el sistema"),
                   ("aviso_diario_al_abrir_caja", "Al abrir la caja"),
                   ("aviso_diario_al_cerrar_caja","Al cerrar la caja")):
        print(f"   {etq:<24}{c.get(k)}")

    sobran = [k for k in ("aviso_diario_al_abrir_app",
                          "aviso_diario_al_abrir_caja",
                          "aviso_diario_al_cerrar_caja") if c.get(k)]
    if not sobran:
        print("\nYa está en modo hora fija: no hay nada que cambiar.")
    else:
        print(f"\n{len(sobran)} disparador(es) por evento están activos.")
        print("Son los que se comen el envío del día.")
        for k in sobran:
            cfg_set(k, False)
        cfg_set("aviso_diario_a_las", True)
        print("\n[OK] Apagados. Queda solo el de hora fija.")

    # Limpiar las marcas del día, para que pueda salir de nuevo hoy
    for k in list(c.keys()):
        if k.startswith("_aviso_diario_ultimo_envio"):
            cfg_set(k, "")
    print("[OK] Marcas del día limpiadas: el próximo envío sale igual.")

    hora = c.get("aviso_diario_hora", 21)
    print(f"\nEl resumen va a salir a las {hora:02d}:00, con el TPV abierto.")
    print("Para cambiar la hora: Config → Aviso diario por email.")


if __name__ == "__main__":
    main()
