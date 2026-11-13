-- ════════════════════════════════════════════════════════════════════════════
-- Módulo de cobro de suscripciones (Facturalo × PagoOK)
-- Tabla NUEVA, ADITIVA. No toca ninguna tabla de emisión.
-- Correr en PGAdmin ANTES del deploy (aunque main.py haga create_all, el índice
-- único PARCIAL de abajo el ORM no lo crea → este SQL es obligatorio primero).
-- ════════════════════════════════════════════════════════════════════════════

CREATE TABLE IF NOT EXISTS suscripcion (
  id                 VARCHAR(36) PRIMARY KEY,
  emisor_id          VARCHAR(36) NOT NULL REFERENCES emisor(id),  -- el CLIENTE suscrito
  plan               VARCHAR(20) NOT NULL,       -- emprendedor | negocio
  periodicidad       VARCHAR(10) NOT NULL,       -- mensual | anual
  monto              NUMERIC(10,2) NOT NULL,
  moneda             VARCHAR(3) DEFAULT 'PEN',
  vence              DATE NOT NULL,              -- hoy + 30 (mensual) / 365 (anual)
  estado             VARCHAR(20) NOT NULL DEFAULT 'pendiente',
     -- pendiente | media | activa | vencida | anulada

  -- Trazabilidad del pago (PagoOK)
  pagook_pago_id     INTEGER,                    -- pago_id devuelto por PagoOK (marcado-usado)
  pagook_nivel       VARCHAR(20),                -- alta | media | voucher
  referencia_externa VARCHAR(150),               -- lo enviado a marcar-usado (= id de esta fila)

  -- Factura de suscripción (PSP). factura_estado = snapshot de comprobante.estado
  -- → distingue 'activa con factura ACEPTADA' de 'activa, factura pendiente/fallida'.
  factura_id         VARCHAR(36) REFERENCES comprobante(id),
  factura_numero     VARCHAR(16),                -- FF50-00000001 (cache legible)
  factura_estado     VARCHAR(32),                -- NULL | pendiente | enviando | aceptado | rechazado...

  pago_voucher_id    VARCHAR(36),                -- si entró por voucher (sin_coincidencia)
  creado_por         VARCHAR(255),
  notas              TEXT,
  creado_en          TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
  actualizado_en     TIMESTAMP WITH TIME ZONE DEFAULT NOW(),

  -- ⚠️ TEMPORAL: 'prueba' agregado para la prueba de fuego S/4 (quitar después).
  CONSTRAINT chk_susc_plan   CHECK (plan IN ('emprendedor','negocio','prueba')),
  CONSTRAINT chk_susc_peri   CHECK (periodicidad IN ('mensual','anual')),
  CONSTRAINT chk_susc_estado CHECK (estado IN ('pendiente','media','activa','vencida','anulada'))
);

CREATE INDEX IF NOT EXISTS idx_susc_emisor         ON suscripcion(emisor_id, vence);
CREATE INDEX IF NOT EXISTS idx_susc_estado         ON suscripcion(estado, vence);
CREATE INDEX IF NOT EXISTS idx_susc_factura_estado ON suscripcion(factura_estado);

-- Anti-doble-cobro LOCAL (además del marcar-usado de PagoOK): un pago → una suscripción.
CREATE UNIQUE INDEX IF NOT EXISTS ux_susc_pagook_pago
  ON suscripcion(pagook_pago_id) WHERE pagook_pago_id IS NOT NULL;
