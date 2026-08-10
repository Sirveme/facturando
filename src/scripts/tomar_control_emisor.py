#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
tomar_control_emisor.py — Reasigna email + resetea contraseña de un emisor, SIN perder
nada más (conserva id, comprobantes, certificados, credenciales). Solo cambia
`email` y `password_hash`.

Ejecutar EN RAILWAY. Edita las 3 constantes de abajo antes de correr (o exporta las
variables de entorno NUEVO_EMAIL / NUEVA_CLAVE).

    Dry-run (no escribe):   python -m src.scripts.tomar_control_emisor
    Aplicar:                python -m src.scripts.tomar_control_emisor --send
"""

import os
import sys

from src.api.dependencies import SessionLocal
from src.models.models import Emisor

# --- EDITA ESTO (o usa variables de entorno) ---
RUC        = '10736459791'
NUEVO_EMAIL = os.getenv('NUEVO_EMAIL', 'TU_EMAIL@ejemplo.com')   # tu email de control
NUEVA_CLAVE = os.getenv('NUEVA_CLAVE', 'CAMBIA_ESTA_CLAVE_1')    # min 8, 1 mayúscula, 1 número

# bcrypt, mismo esquema que src/api/registro.py
from passlib.context import CryptContext
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def main():
    send = '--send' in sys.argv
    print("=" * 72)
    print(f"TOMAR CONTROL — emisor RUC {RUC}")
    print("MODO:", "🚨 APLICAR" if send else "🧪 DRY-RUN (sin escribir)")
    print("=" * 72)

    if send and (NUEVO_EMAIL == 'TU_EMAIL@ejemplo.com' or NUEVA_CLAVE == 'CAMBIA_ESTA_CLAVE_1'):
        print("🛑 Edita NUEVO_EMAIL y NUEVA_CLAVE (o expórtalos) antes de --send.")
        sys.exit(1)
    if send and (len(NUEVA_CLAVE) < 8 or NUEVA_CLAVE.isalpha() or NUEVA_CLAVE.isdigit()
                 or NUEVA_CLAVE.upper() == NUEVA_CLAVE or NUEVA_CLAVE.lower() == NUEVA_CLAVE):
        print("🛑 La clave debe tener min 8 chars, al menos 1 mayúscula y 1 número.")
        sys.exit(1)

    db = SessionLocal()
    try:
        e = db.query(Emisor).filter(Emisor.ruc == RUC).first()
        if not e:
            print(f"🛑 No existe emisor con RUC {RUC}."); sys.exit(1)

        print(f"  id           : {e.id}")
        print(f"  email actual : {e.email}")
        print(f"  email nuevo  : {NUEVO_EMAIL}")
        print(f"  clave        : {'*' * len(NUEVA_CLAVE)} (se guardará hasheada bcrypt)")

        # Chequear que el email nuevo no lo use otro emisor
        otro = (db.query(Emisor)
                .filter(Emisor.email == NUEVO_EMAIL.strip().lower(), Emisor.id != e.id)
                .first())
        if otro:
            print(f"🛑 El email {NUEVO_EMAIL} ya está en uso por otro emisor (id={otro.id})."); sys.exit(1)

        if not send:
            print("\n🧪 DRY-RUN: no se escribió. Para aplicar: --send")
            return

        e.email = NUEVO_EMAIL.strip().lower()
        e.password_hash = pwd_context.hash(NUEVA_CLAVE[:72])
        db.commit()
        print("\n✅ Listo: email y contraseña actualizados. Ya puedes loguearte en /login con esas credenciales.")
    finally:
        db.close()


if __name__ == '__main__':
    main()
