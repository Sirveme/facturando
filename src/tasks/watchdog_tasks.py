#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
watchdog_tasks.py — Latido del worker para el vigilante de salud.

El worker escribe watchdog:heartbeat (timestamp epoch) en Redis:
  - en CADA tarea que ejecuta (señal task_postrun) → prueba que CONSUME de verdad;
  - al procesar la tarea watchdog_ping que el cron encola cada corrida (cubre el
    worker ocioso pero sano).

NO toca envio_sunat.py ni la emisión: la señal está desacoplada. Si Redis falla,
es no-fatal (el latido simplemente no se actualiza; el vigilante lo detectará).
"""
import logging
import time

from celery.signals import task_postrun

from src.core.config import settings
from src.tasks.celery_app import celery_app

logger = logging.getLogger(__name__)

HEARTBEAT_KEY = "watchdog:heartbeat"

try:
    import redis as _redis
except Exception:  # pragma: no cover
    _redis = None


def _escribir_latido():
    if _redis is None or not settings.redis_url:
        return
    try:
        c = _redis.from_url(settings.redis_url)
        c.set(HEARTBEAT_KEY, str(time.time()))
    except Exception as e:
        logger.warning("[watchdog] no se pudo escribir latido: %s", e)


@celery_app.task(name="watchdog_ping")
def watchdog_ping():
    """Tarea mínima: el worker la consume y deja constancia de que está vivo."""
    _escribir_latido()
    return {"ok": True, "ts": time.time()}


@task_postrun.connect
def _latido_en_cada_tarea(**kwargs):
    # Se dispara tras CUALQUIER tarea ejecutada por el worker → latido fresco con tráfico real.
    _escribir_latido()
