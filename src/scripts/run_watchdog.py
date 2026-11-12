#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
run_watchdog.py — Runner del vigilante de salud. Pensado para el SERVICIO CRON de
Railway (*/15 * * * *): corre UNA vez las 4 revisiones + snapshot y sale.

USO:
    python -m src.scripts.run_watchdog              # corrida normal (envía alertas)
    python -m src.scripts.run_watchdog --no-enviar  # corre checks SIN mandar Telegram
    python -m src.scripts.run_watchdog --test       # solo manda un mensaje de prueba y sale
"""
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass


def main():
    if '--test' in sys.argv:
        from src.services.telegram_notify import enviar_telegram, telegram_configurado
        if not telegram_configurado():
            print("🛑 Falta TELEGRAM_BOT_TOKEN/CHAT_ID en el entorno.")
            sys.exit(1)
        ok = enviar_telegram("✅ Vigilante de Facturalo: mensaje de PRUEBA. Si lees esto, Telegram funciona.")
        print("Mensaje de prueba:", "ENVIADO ✅" if ok else "FALLÓ ❌")
        sys.exit(0 if ok else 1)

    from src.services.watchdog import correr_watchdog
    enviar = '--no-enviar' not in sys.argv
    rep = correr_watchdog(enviar=enviar)
    print("[watchdog] report:", rep)


if __name__ == '__main__':
    main()
