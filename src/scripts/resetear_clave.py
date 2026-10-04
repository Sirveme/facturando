#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
resetear_clave.py — READ/WRITE mínimo. Resetea la contraseña de UN emisor
(password_hash) a una clave que tú eliges. Hash bcrypt idéntico al registro
(CryptContext['bcrypt'], truncado a 72) → el login la acepta.

Flujo seguro: PRIMERO muestra el emisor (RUC, razón social, email) y valida la
clave; solo ESCRIBE con --confirm.

USO (en Railway):
    # 1) ver el emisor + validar la clave (dry-run, NO escribe):
    python -m src.scripts.resetear_clave <RUC> "MiClaveNueva1"
    # 2) aplicar el cambio:
    python -m src.scripts.resetear_clave <RUC> "MiClaveNueva1" --confirm

Política de clave (igual que el registro): mínimo 8, al menos 1 mayúscula y 1 número.
"""
import re
import sys
from datetime import datetime, timezone

from passlib.context import CryptContext

from src.api.dependencies import SessionLocal
from src.models.models import Emisor

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")  # idéntico a registro.py


def _validar_password(p):
    if len(p) < 8:
        return False, "La contraseña debe tener mínimo 8 caracteres"
    if not re.search(r'[A-Z]', p):
        return False, "Debe contener al menos una mayúscula"
    if not re.search(r'[0-9]', p):
        return False, "Debe contener al menos un número"
    return True, ""


def _abort(msg):
    print(f"\n🛑 {msg}\n")
    sys.exit(1)


def main():
    pos = [a for a in sys.argv[1:] if not a.startswith('--')]
    confirm = '--confirm' in sys.argv
    if len(pos) < 2:
        print(__doc__)
        sys.exit(1)
    ruc, nueva = pos[0].strip(), pos[1]

    ok_pwd, msg = _validar_password(nueva)
    if not ok_pwd:
        _abort(f"Clave inválida: {msg}")

    db = SessionLocal()
    try:
        emisor = db.query(Emisor).filter(Emisor.ruc == ruc).first()
        if not emisor:
            _abort(f"No existe emisor con RUC {ruc}")

        print("=" * 72)
        print("EMISOR A MODIFICAR (confirma que es el correcto):")
        print(f"  RUC           : {emisor.ruc}")
        print(f"  Razón social  : {emisor.razon_social}")
        print(f"  Email         : {emisor.email}")
        print(f"  Tiene clave   : {'sí' if emisor.password_hash else 'no'}")
        print(f"  Nueva clave   : {'*' * len(nueva)} ({len(nueva)} caracteres)")
        print("=" * 72)

        if not confirm:
            print("[DRY-RUN] Clave válida y emisor encontrado. Para aplicar, re-ejecuta con --confirm.")
            return

        emisor.password_hash = pwd_context.hash(nueva[:72])
        if hasattr(emisor, 'actualizado_en'):
            emisor.actualizado_en = datetime.now(timezone.utc)
        db.commit()
        print(f"✅ Contraseña actualizada para {emisor.ruc} — {emisor.razon_social}.")
        print("   Ya puedes iniciar sesión en /login con esa clave.")
    finally:
        db.close()


if __name__ == '__main__':
    main()
