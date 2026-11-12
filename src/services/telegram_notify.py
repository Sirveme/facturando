#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
telegram_notify.py — Envío de mensajes a Telegram para el vigilante de salud.

Lee TELEGRAM_BOT_TOKEN y TELEGRAM_CHAT_ID de la configuración (env de Railway).
NUNCA hardcodear el token. NO-FATAL: si falla o faltan credenciales, registra y
devuelve False, sin levantar excepción (el monitoreo jamás debe romper el flujo).
"""
import logging

import requests

from src.core.config import settings

logger = logging.getLogger(__name__)

_API = "https://api.telegram.org/bot{token}/sendMessage"


def telegram_configurado() -> bool:
    return bool(settings.TELEGRAM_BOT_TOKEN and settings.TELEGRAM_CHAT_ID)


def enviar_telegram(texto: str) -> bool:
    """POST a la API de Telegram. Devuelve True si se envió (HTTP 200)."""
    token = settings.TELEGRAM_BOT_TOKEN
    chat_id = settings.TELEGRAM_CHAT_ID
    if not token or not chat_id:
        logger.warning("[telegram] Falta TELEGRAM_BOT_TOKEN/CHAT_ID — mensaje omitido")
        return False
    try:
        resp = requests.post(
            _API.format(token=token),
            json={
                "chat_id": chat_id,
                "text": texto,
                "parse_mode": "HTML",
                "disable_web_page_preview": True,
            },
            timeout=10,
        )
        if resp.status_code == 200:
            return True
        logger.warning("[telegram] HTTP %s: %s", resp.status_code, resp.text[:200])
        return False
    except Exception as e:
        logger.warning("[telegram] Error enviando: %s", e)
        return False
