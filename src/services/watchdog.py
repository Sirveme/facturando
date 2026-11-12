#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
watchdog.py — Vigilante de salud de Facturalo (SOLO LECTURA de BD/Redis + Telegram).

NO toca emisión ni XML. Corre fuera del worker (servicio cron) para seguir vivo
aunque el worker esté colgado. Hace 4 revisiones, aplica anti-spam, arma el snapshot
por cliente y encola un watchdog_ping para medir el latido real del worker.

Claves Redis:
  watchdog:heartbeat        -> epoch del último latido que escribió el worker
  watchdog:last_ping        -> epoch del último ping que encolamos (ack del worker)
  watchdog:first_seen       -> epoch de la primera corrida (para no falsear al arrancar)
  watchdog:alerted:<tipo>   -> epoch del último aviso de ese tipo (anti-spam)
  watchdog:last_rechazo_ts  -> marca de agua (epoch) para no repetir rechazos viejos
  watchdog:snapshot         -> JSON del último estado por cliente (lo lee /revisar)
"""
import json
import logging
import time
from datetime import datetime, timezone, timedelta

from sqlalchemy import func

from src.core.config import settings
from src.services.telegram_notify import enviar_telegram

logger = logging.getLogger(__name__)

try:
    import redis as _redis
except Exception:  # pragma: no cover
    _redis = None

LIMA = timezone(timedelta(hours=-5))

RUCS_VIGILADOS = {
    '20103830991': 'CCPL',
    '10467016283': 'Restaurante Gourmet',
    '10736459791': 'Maykol',
}

HEARTBEAT_KEY = "watchdog:heartbeat"


# ───────────────────────────── helpers de tiempo / redis ─────────────────────────────
def _redis_client():
    if _redis is None or not settings.redis_url:
        return None
    try:
        return _redis.from_url(settings.redis_url)
    except Exception as e:
        logger.warning("[watchdog] Redis no disponible: %s", e)
        return None


def _utc_naive(dt_aware):
    return dt_aware.astimezone(timezone.utc).replace(tzinfo=None)


def _ahora_lima():
    return datetime.now(LIMA)


def _rget(r, key):
    try:
        v = r.get(key)
        return v.decode() if isinstance(v, (bytes, bytearray)) else v
    except Exception:
        return None


# ───────────────────────────── anti-spam ─────────────────────────────
def _debe_avisar(r, tipo) -> bool:
    """True si hay que avisar: sin aviso previo, o pasó el cooldown."""
    last = _rget(r, f"watchdog:alerted:{tipo}")
    if not last:
        return True
    try:
        return (time.time() - float(last)) >= settings.WD_COOLDOWN_MIN * 60
    except Exception:
        return True


def _marcar_avisado(r, tipo):
    try:
        r.set(f"watchdog:alerted:{tipo}", str(time.time()))
    except Exception:
        pass


def _resolver(r, tipo):
    """El problema ya no ocurre → limpiar la bandera (el próximo caso avisa de inmediato)."""
    try:
        r.delete(f"watchdog:alerted:{tipo}")
    except Exception:
        pass


def _aplicar(r, tipo, problema, mensaje, enviar, report):
    if problema:
        if _debe_avisar(r, tipo):
            enviado = enviar_telegram(mensaje) if enviar else False
            _marcar_avisado(r, tipo)
            report[tipo] = {"alerta": True, "enviado": enviado, "msg": mensaje}
        else:
            report[tipo] = {"alerta": True, "enviado": False, "cooldown": True, "msg": mensaje}
    else:
        _resolver(r, tipo)
        report[tipo] = {"alerta": False}


# ───────────────────────────── las 4 revisiones ─────────────────────────────
def check_cola(db):
    estados = [s.strip() for s in settings.WD_ESTADOS_COLA.split(',') if s.strip()]
    ahora = datetime.utcnow()
    corte_min = ahora - timedelta(minutes=settings.WD_COLA_MIN)
    corte_max = ahora - timedelta(hours=settings.WD_COLA_MAX_H)
    from src.models.models import Comprobante
    n = (db.query(func.count(Comprobante.id))
         .filter(Comprobante.estado.in_(estados),
                 Comprobante.creado_en < corte_min,
                 Comprobante.creado_en > corte_max).scalar()) or 0
    if n > 0:
        return True, (f"⚠️ Hay {n} comprobantes encolados hace más de "
                      f"{settings.WD_COLA_MIN} min. El worker podría estar caído.")
    return False, None


def check_latido(r):
    """Mide el consumo REAL. Devuelve (problema, mensaje). NO encola el ping (eso lo hace el runner)."""
    ahora = time.time()
    hb = _rget(r, HEARTBEAT_KEY)
    last_ping = _rget(r, "watchdog:last_ping")
    if not hb:
        first = _rget(r, "watchdog:first_seen")
        if not first:
            try:
                r.set("watchdog:first_seen", str(ahora))
            except Exception:
                pass
            return False, None
        if (ahora - float(first)) > settings.WD_HEARTBEAT_MIN * 60:
            return True, ("🔴 El worker Celery nunca dio señal de vida "
                          f"(+{settings.WD_HEARTBEAT_MIN} min sin latido). Puede figurar Online igual.")
        return False, None
    edad_min = (ahora - float(hb)) / 60.0
    stuck = edad_min > settings.WD_HEARTBEAT_MIN
    if last_ping:
        try:
            if float(hb) < float(last_ping):   # no procesó el ping de la corrida anterior
                stuck = True
        except Exception:
            pass
    if stuck:
        return True, (f"🔴 El worker Celery no consume tareas hace más de {int(edad_min)} min "
                      f"(el contenedor puede figurar Online igual).")
    return False, None


def check_rechazos(db, r, enviar):
    """Avisa por cada comprobante NUEVO rechazado (marca de agua por recibido_en)."""
    from src.models.models import Comprobante, Emisor, RespuestaSunat
    wm = _rget(r, "watchdog:last_rechazo_ts")
    ahora = time.time()
    if not wm:
        # Primera vez: fijar marca de agua AHORA (no avisar históricos).
        try:
            r.set("watchdog:last_rechazo_ts", str(ahora))
        except Exception:
            pass
        return []
    wm_dt = datetime.utcfromtimestamp(float(wm))
    rows = (db.query(Comprobante, Emisor, RespuestaSunat)
            .join(RespuestaSunat, RespuestaSunat.comprobante_id == Comprobante.id)
            .join(Emisor, Emisor.id == Comprobante.emisor_id)
            .filter(Comprobante.estado == 'rechazado',
                    RespuestaSunat.recibido_en > wm_dt)
            .order_by(RespuestaSunat.recibido_en.asc()).limit(20).all())
    avisados = []
    max_ts = float(wm)
    for comp, em, resp in rows:
        msg = (f"❌ Comprobante {comp.numero_formato} de {em.razon_social} "
               f"RECHAZADO por SUNAT: {(resp.descripcion or resp.codigo_cdr or '')[:150]}")
        if enviar:
            enviar_telegram(msg)
        avisados.append({"numero": comp.numero_formato, "emisor": em.ruc, "codigo": resp.codigo_cdr})
        if resp.recibido_en:
            rdt = resp.recibido_en if resp.recibido_en.tzinfo else resp.recibido_en.replace(tzinfo=timezone.utc)
            max_ts = max(max_ts, rdt.timestamp())
    try:
        r.set("watchdog:last_rechazo_ts", str(max_ts))
    except Exception:
        pass
    return avisados


def check_no_emitio(db, r, enviar, report):
    now_lima = _ahora_lima()
    if now_lima.hour < settings.WD_NOEMISION_HORA_LIMA:
        return  # aún no es la hora de control
    from src.models.models import Comprobante, Emisor
    hoy0 = _utc_naive(now_lima.replace(hour=0, minute=0, second=0, microsecond=0))
    for ruc, nombre in RUCS_VIGILADOS.items():
        em = db.query(Emisor).filter(Emisor.ruc == ruc).first()
        if not em:
            continue
        n = (db.query(func.count(Comprobante.id))
             .filter(Comprobante.emisor_id == em.id, Comprobante.creado_en >= hoy0).scalar()) or 0
        msg = f"🟡 {nombre} no ha emitido comprobantes hoy (suele emitir a diario)."
        _aplicar(r, f"noemision:{ruc}", n == 0, msg, enviar, report)


# ───────────────────────────── snapshot por cliente ─────────────────────────────
def _resumen_comp(comp):
    if not comp:
        return None
    hora = '—'
    if comp.creado_en:
        dt = comp.creado_en if comp.creado_en.tzinfo else comp.creado_en.replace(tzinfo=timezone.utc)
        hora = dt.astimezone(LIMA).strftime('%H:%M')  # hora Lima, no UTC
    return {"numero": comp.numero_formato, "estado": comp.estado, "hora": hora,
            "total": float(comp.monto_total or 0)}


def construir_snapshot(db):
    from src.models.models import Comprobante, Emisor
    now_lima = _ahora_lima()
    hoy0 = _utc_naive(now_lima.replace(hour=0, minute=0, second=0, microsecond=0))
    ayer0 = hoy0 - timedelta(days=1)
    clientes = []
    for ruc, nombre in RUCS_VIGILADOS.items():
        em = db.query(Emisor).filter(Emisor.ruc == ruc).first()
        if not em:
            clientes.append({"ruc": ruc, "nombre": nombre, "falta_emisor": True})
            continue
        base = db.query(Comprobante).filter(Comprobante.emisor_id == em.id)
        ultimo_ayer = (base.filter(Comprobante.creado_en >= ayer0, Comprobante.creado_en < hoy0)
                       .order_by(Comprobante.creado_en.desc()).first())
        hoy_q = base.filter(Comprobante.creado_en >= hoy0)
        primero_hoy = hoy_q.order_by(Comprobante.creado_en.asc()).first()
        ultimo_hoy = hoy_q.order_by(Comprobante.creado_en.desc()).first()
        total_hoy = (db.query(func.count(Comprobante.id))
                     .filter(Comprobante.emisor_id == em.id, Comprobante.creado_en >= hoy0).scalar()) or 0
        clientes.append({
            "ruc": ruc, "nombre": nombre,
            "ultimo_ayer": _resumen_comp(ultimo_ayer),
            "primero_hoy": _resumen_comp(primero_hoy),
            "ultimo_hoy": _resumen_comp(ultimo_hoy),
            "total_hoy": total_hoy,
        })
    return {"generado_en": now_lima.strftime('%Y-%m-%d %H:%M:%S'), "tz": "America/Lima",
            "clientes": clientes}


# ───────────────────────────── orquestador ─────────────────────────────
def correr_watchdog(enviar=True):
    """Corre las 4 revisiones + snapshot + encola el ping. Devuelve el report (dict)."""
    from src.api.dependencies import SessionLocal
    r = _redis_client()
    report = {"ts": time.time(), "enviar": enviar}
    db = SessionLocal()
    try:
        if r is None:
            report["error"] = "redis_no_disponible"
            return report

        # 1) Cola atascada
        prob, msg = check_cola(db)
        _aplicar(r, "cola", prob, msg, enviar, report)

        # 2) Worker sin latido
        prob, msg = check_latido(r)
        _aplicar(r, "latido", prob, msg, enviar, report)

        # 3) Rechazos nuevos (marca de agua)
        report["rechazos"] = check_rechazos(db, r, enviar)

        # 4) No emitió hoy (después de las 20:00 Lima)
        check_no_emitio(db, r, enviar, report)

        # Snapshot por cliente → Redis (lo lee /revisar)
        snap = construir_snapshot(db)
        try:
            r.set("watchdog:snapshot", json.dumps(snap, ensure_ascii=False))
        except Exception as e:
            logger.warning("[watchdog] no se pudo guardar snapshot: %s", e)
        report["snapshot_ok"] = True

        # Encolar el ping y registrar su marca (ack del worker en la próxima corrida)
        try:
            from src.tasks.celery_app import celery_app
            celery_app.send_task("watchdog_ping")
            r.set("watchdog:last_ping", str(time.time()))
            report["ping_encolado"] = True
        except Exception as e:
            logger.warning("[watchdog] no se pudo encolar watchdog_ping: %s", e)
            report["ping_encolado"] = False

        return report
    finally:
        db.close()


def leer_snapshot():
    r = _redis_client()
    if r is None:
        return None
    raw = _rget(r, "watchdog:snapshot")
    if not raw:
        return None
    try:
        return json.loads(raw)
    except Exception:
        return None
