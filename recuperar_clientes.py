import sqlite3
import shutil
import os
from datetime import datetime

actual = "tpv2.db"
backup = "backups/tpv2_2026-09-19_11-45_inicio.db"

# 1. Copia de seguridad de la base actual
fecha = datetime.now().strftime("%Y%m%d_%H%M%S")
copia = f"tpv2_ANTES_RECUPERAR_CLIENTES_{fecha}.db"
shutil.copy2(actual, copia)

print("Copia de seguridad creada:", copia)

# 2. Leer clientes del backup
con_backup = sqlite3.connect(backup)
clientes = con_backup.execute("""
    SELECT id, dni, nombre, telefono, tope_credito, activo, creado_en
    FROM clientes
    ORDER BY id
""").fetchall()
con_backup.close()

print("\nClientes encontrados en backup:")
for c in clientes:
    print(c)

# 3. Abrir base actual
con = sqlite3.connect(actual)

# Verificar que actualmente no haya clientes
cantidad = con.execute("SELECT COUNT(*) FROM clientes").fetchone()[0]
print("\nClientes actuales antes de recuperar:", cantidad)

# 4. Insertar los clientes del backup
con.executemany("""
    INSERT INTO clientes
    (id, dni, nombre, telefono, tope_credito, activo, creado_en)
    VALUES (?, ?, ?, ?, ?, ?, ?)
""", clientes)

con.commit()

# 5. Verificaciones
clientes_final = con.execute("SELECT COUNT(*) FROM clientes").fetchone()[0]
cuentas = con.execute("SELECT COUNT(*) FROM cuentas_corrientes").fetchone()[0]
movimientos = con.execute("SELECT COUNT(*) FROM movimientos_cuenta").fetchone()[0]

print("\nRESULTADO:")
print("Clientes:", clientes_final)
print("Cuentas corrientes:", cuentas)
print("Movimientos:", movimientos)

print("\nClientes recuperados:")
for c in con.execute("""
    SELECT id, dni, nombre, telefono, tope_credito, activo, creado_en
    FROM clientes
    ORDER BY id
"""):
    print(c)

con.close()
