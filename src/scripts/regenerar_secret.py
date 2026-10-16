#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
regenerar_secret.py — READ/WRITE mínimo. Regenera el API Secret de UN emisor
(identificado por RUC) CONSERVANDO su API Key. Guarda el secret como hash
SHA-256 (idéntico a generar_api_credentials en src/api/registro.py y a la
validación en src/api/v1/auth.py), para que la API lo acepte.

Seguridad:
  - Afecta SOLO al emisor del RUC indicado.
  - Muestra el emisor y pide CONFIRMACIÓN escribiendo el RUC antes de tocar la BD.
  - Imprime el secret EN CLARO UNA sola vez en pantalla. NO lo escribe en logs
    ni en archivos (en la BD solo queda el hash).

USO (ver instrucciones de ejecución en docs/pendientes.md):
    python -m src.scripts.regenerar_secret <RUC>
    # Hoy: 20616219686 (MITA)
"""
import sys
import hashlib
import secrets
from datetime import datetime, timezone

from src.api.dependencies import SessionLocal
from src.models.models import Emisor

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass


def _mask(v):
    """Oculta la mayor parte de la API Key (solo para identificar, no exponer)."""
    if not v:
        return "(vacío)"
    return (v[:8] + "…" + v[-4:]) if len(v) > 14 else v


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    if len(args) != 1:
        print(__doc__)
        sys.exit(1)
    ruc = args[0].strip()

    db = SessionLocal()
    try:
        emisor = db.query(Emisor).filter(Emisor.ruc == ruc).first()
        if not emisor:
            print(f"\n🛑 No existe emisor con RUC {ruc}. No se cambió nada.\n")
            sys.exit(1)

        print("=" * 72)
        print("EMISOR A MODIFICAR (regenerar API Secret) — confirma que es el correcto:")
        print(f"  RUC            : {emisor.ruc}")
        print(f"  Razón social   : {emisor.razon_social}")
        print(f"  API Key        : {_mask(emisor.api_key)}   (SE CONSERVA, no cambia)")
        print(f"  API activa     : {getattr(emisor, 'api_activa', None)}")
        print(f"  Producción     : {getattr(emisor, 'produccion', None)}")
        print(f"  Secret actual  : {'(definido)' if emisor.api_secret else '(vacío)'} — hash, no se puede mostrar")
        print("=" * 72)
        print("⚠️  Esto INVALIDA el secret anterior. Todo sistema que facture con este")
        print("    emisor deberá actualizar su header X-API-Secret con el NUEVO valor.")
        print()

        confirm = input(f"Para confirmar, escribe el RUC exacto ({ruc}): ").strip()
        if confirm != ruc:
            print("\n🛑 El RUC no coincide. Cancelado — no se cambió nada.\n")
            sys.exit(1)

        # Nuevo secret: MISMO formato que generar_api_credentials (token_hex(32) → sha256).
        nuevo_secret = secrets.token_hex(32)
        nuevo_hash = hashlib.sha256(nuevo_secret.encode()).hexdigest()

        emisor.api_secret = nuevo_hash
        if hasattr(emisor, "actualizado_en"):
            emisor.actualizado_en = datetime.now(timezone.utc)
        db.commit()

        print(f"\n✅ API Secret regenerado para {emisor.ruc} — {emisor.razon_social}")
        print(f"   La API Key NO cambió: {_mask(emisor.api_key)}")
        print()
        print("┌───────────────────────────────────────────────────────────────────────┐")
        print("│  NUEVO API SECRET (se muestra UNA sola vez — cópialo AHORA):            │")
        print("└───────────────────────────────────────────────────────────────────────┘")
        print()
        print("   " + nuevo_secret)
        print()
        print("   Guárdalo seguro. No se vuelve a mostrar (en la BD solo queda el hash).")
        print()
    finally:
        db.close()


if __name__ == "__main__":
    main()
