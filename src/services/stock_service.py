"""
Servicio de stock básico sobre la tabla `producto` existente (multi-tenant por
emisor). El stock vive en producto.stock_actual; el kardex en movimientos_stock.

- registrar_movimiento: actualiza producto.stock_actual atómicamente
  (UPDATE ... RETURNING) y graba el movimiento con saldo_resultante. Permite
  stock negativo (solo advierte por log, no bloquea). Los movimientos MANUALES
  se permiten aunque maneja_stock sea False (la UI lo advierte).
- descontar_por_comprobante: salida por cada línea de factura/boleta cuyo
  codigo coincida con producto.codigo_interno. Productos con maneja_stock=False
  se omiten (log INFO).
- descontar_por_guia: igual con ítems de la GRE, pero solo si la guía NO está
  vinculada a una factura (anti doble descuento).
- revertir_por_origen: entradas inversas si un documento se anula/rechaza.

Idempotencia: descontar_por_* no vuelve a descontar si ya existe un movimiento
para ese origen (origen_tipo, origen_id).
"""
import logging
from decimal import Decimal

from sqlalchemy import text

from src.models.models import (
    Producto, MovimientoStock, Comprobante, GuiaRemision, peru_now,
)

logger = logging.getLogger(__name__)

TIPOS_VALIDOS = ("entrada", "salida", "ajuste")


def _dec(valor) -> Decimal:
    try:
        return Decimal(str(valor or 0))
    except Exception:
        return Decimal("0")


def registrar_movimiento(db, emisor_id, producto_id, tipo, cantidad,
                         origen_tipo=None, origen_id=None, glosa=None):
    """Registra un movimiento de stock y actualiza producto.stock_actual
    atómicamente. 'entrada' suma, 'salida' resta, 'ajuste' usa cantidad con
    signo. Devuelve el MovimientoStock creado."""
    if tipo not in TIPOS_VALIDOS:
        raise ValueError(f"tipo de movimiento inválido: {tipo}")

    cantidad = _dec(cantidad)
    if tipo == "salida":
        delta = -abs(cantidad)
    elif tipo == "entrada":
        delta = abs(cantidad)
    else:  # ajuste: cantidad con signo
        delta = cantidad

    # UPDATE atómico con RETURNING del saldo nuevo (evita carreras de lectura).
    fila = db.execute(
        text(
            "UPDATE producto SET stock_actual = COALESCE(stock_actual, 0) + :delta, "
            "actualizado_en = now() WHERE id = :pid AND emisor_id = :eid "
            "RETURNING stock_actual"
        ),
        {"delta": delta, "pid": producto_id, "eid": emisor_id},
    ).fetchone()

    if fila is None:
        raise ValueError(f"Producto {producto_id} no existe para el emisor {emisor_id}")

    saldo = _dec(fila[0])
    if saldo < 0:
        logger.warning("[STOCK] Producto %s quedó con stock negativo: %s", producto_id, saldo)

    mov = MovimientoStock(
        emisor_id=emisor_id,
        producto_id=producto_id,
        tipo=tipo,
        cantidad=delta,
        saldo_resultante=saldo,
        origen_tipo=origen_tipo,
        origen_id=origen_id,
        glosa=glosa,
        fecha=peru_now(),
    )
    db.add(mov)
    db.commit()
    logger.info("[STOCK] %s %s cant=%s saldo=%s (origen=%s:%s)",
                tipo, producto_id, delta, saldo, origen_tipo, origen_id)
    return mov


def _ya_procesado(db, origen_tipo, origen_id) -> bool:
    if not origen_id:
        return False
    existe = (
        db.query(MovimientoStock.id)
        .filter(MovimientoStock.origen_tipo == origen_tipo,
                MovimientoStock.origen_id == origen_id)
        .first()
    )
    return existe is not None


def _producto_por_codigo(db, emisor_id, codigo):
    """Busca un producto activo del emisor por su codigo_interno."""
    if not codigo:
        return None
    return (
        db.query(Producto)
        .filter(Producto.emisor_id == emisor_id,
                Producto.codigo_interno == codigo,
                Producto.activo.is_(True))
        .first()
    )


def descontar_por_comprobante(db, comprobante_id):
    """Descuenta stock por cada línea de la factura/boleta cuyo código coincida
    con producto.codigo_interno. Productos con maneja_stock=False se omiten.
    Líneas sin producto coincidente se ignoran (log INFO). Idempotente."""
    comp = db.query(Comprobante).filter(Comprobante.id == comprobante_id).first()
    if not comp:
        logger.info("[STOCK] Comprobante %s no encontrado; nada que descontar", comprobante_id)
        return []

    if _ya_procesado(db, "comprobante", comprobante_id):
        logger.info("[STOCK] Comprobante %s ya descontó stock; se omite", comprobante_id)
        return []

    movimientos = []
    for linea in (comp.lineas or []):
        prod = _producto_por_codigo(db, comp.emisor_id, getattr(linea, "codigo", None))
        if not prod:
            logger.info("[STOCK] Línea sin producto (codigo=%s) en comp %s; ignorada",
                        getattr(linea, "codigo", None), comprobante_id)
            continue
        if not prod.maneja_stock:
            logger.info("[STOCK] Producto %s no maneja stock; salida omitida (comp %s)",
                        prod.codigo_interno, comprobante_id)
            continue
        glosa = f"Salida por {comp.tipo_documento} {comp.serie}-{comp.numero}"
        movimientos.append(registrar_movimiento(
            db, comp.emisor_id, prod.id, "salida", linea.cantidad,
            origen_tipo="comprobante", origen_id=comprobante_id, glosa=glosa,
        ))
    return movimientos


def descontar_por_guia(db, guia_id):
    """Descuenta stock por cada ítem de la GRE, solo si la guía NO tiene
    comprobante_id (si está vinculada a una factura, descuenta la factura).
    Productos con maneja_stock=False se omiten. Idempotente."""
    guia = db.query(GuiaRemision).filter(GuiaRemision.id == guia_id).first()
    if not guia:
        logger.info("[STOCK] Guía %s no encontrada; nada que descontar", guia_id)
        return []

    if guia.comprobante_id:
        logger.info("[STOCK] Guía %s vinculada a factura %s; no se descuenta (anti doble descuento)",
                    guia_id, guia.comprobante_id)
        return []

    if _ya_procesado(db, "guia", guia_id):
        logger.info("[STOCK] Guía %s ya descontó stock; se omite", guia_id)
        return []

    movimientos = []
    for item in (guia.items or []):
        prod = _producto_por_codigo(db, guia.emisor_id, getattr(item, "codigo", None))
        if not prod:
            logger.info("[STOCK] Ítem sin producto (codigo=%s) en guía %s; ignorado",
                        getattr(item, "codigo", None), guia_id)
            continue
        if not prod.maneja_stock:
            logger.info("[STOCK] Producto %s no maneja stock; salida omitida (guía %s)",
                        prod.codigo_interno, guia_id)
            continue
        glosa = f"Salida por GRE {guia.serie}-{guia.numero}"
        movimientos.append(registrar_movimiento(
            db, guia.emisor_id, prod.id, "salida", item.cantidad,
            origen_tipo="guia", origen_id=guia_id, glosa=glosa,
        ))
    return movimientos


def revertir_por_origen(db, origen_tipo, origen_id):
    """Revierte (movimientos inversos) los de un origen ya descontado, si el
    documento se anula/rechaza. Idempotente: no duplica reversiones."""
    if not origen_id:
        return []

    movs = (
        db.query(MovimientoStock)
        .filter(MovimientoStock.origen_tipo == origen_tipo,
                MovimientoStock.origen_id == origen_id)
        .all()
    )
    originales = [m for m in movs if not (m.glosa or "").startswith("Reversión")]
    ya_revertido = any((m.glosa or "").startswith("Reversión") for m in movs)
    if not originales or ya_revertido:
        logger.info("[STOCK] Nada que revertir para %s:%s (revertido=%s)",
                    origen_tipo, origen_id, ya_revertido)
        return []

    reversiones = []
    for m in originales:
        cantidad_inv = abs(_dec(m.cantidad))
        tipo_inv = "entrada" if _dec(m.cantidad) < 0 else "salida"
        glosa = f"Reversión {origen_tipo} {origen_id}"
        reversiones.append(registrar_movimiento(
            db, m.emisor_id, m.producto_id, tipo_inv, cantidad_inv,
            origen_tipo=origen_tipo, origen_id=origen_id, glosa=glosa,
        ))
    return reversiones
