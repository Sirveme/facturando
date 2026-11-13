-- ════════════════════════════════════════════════════════════════════════════
-- SINCRONIZA la tabla `suscripcion` con el modelo (models.py).
-- Idempotente: ADD COLUMN IF NOT EXISTS → las que ya existen se omiten; las que
-- falten (p. ej. factura_estado) se crean. No falla, se puede correr varias veces.
-- Correr en PGAdmin. Se agregan NULLABLE a propósito (seguro aunque haya filas);
-- el NOT NULL de las obligatorias ya vino del CREATE original y el modelo lo valida.
-- ════════════════════════════════════════════════════════════════════════════

ALTER TABLE suscripcion ADD COLUMN IF NOT EXISTS emisor_id          VARCHAR(36);
ALTER TABLE suscripcion ADD COLUMN IF NOT EXISTS plan               VARCHAR(20);
ALTER TABLE suscripcion ADD COLUMN IF NOT EXISTS periodicidad       VARCHAR(10);
ALTER TABLE suscripcion ADD COLUMN IF NOT EXISTS monto              NUMERIC(10,2);
ALTER TABLE suscripcion ADD COLUMN IF NOT EXISTS moneda             VARCHAR(3) DEFAULT 'PEN';
ALTER TABLE suscripcion ADD COLUMN IF NOT EXISTS vence              DATE;
ALTER TABLE suscripcion ADD COLUMN IF NOT EXISTS estado             VARCHAR(20) DEFAULT 'pendiente';
ALTER TABLE suscripcion ADD COLUMN IF NOT EXISTS pagook_pago_id     INTEGER;
ALTER TABLE suscripcion ADD COLUMN IF NOT EXISTS pagook_nivel       VARCHAR(20);
ALTER TABLE suscripcion ADD COLUMN IF NOT EXISTS referencia_externa VARCHAR(150);
ALTER TABLE suscripcion ADD COLUMN IF NOT EXISTS factura_id         VARCHAR(36);
ALTER TABLE suscripcion ADD COLUMN IF NOT EXISTS factura_numero     VARCHAR(16);
ALTER TABLE suscripcion ADD COLUMN IF NOT EXISTS factura_estado     VARCHAR(32);   -- ← la que faltaba
ALTER TABLE suscripcion ADD COLUMN IF NOT EXISTS pago_voucher_id    VARCHAR(36);
ALTER TABLE suscripcion ADD COLUMN IF NOT EXISTS creado_por         VARCHAR(255);
ALTER TABLE suscripcion ADD COLUMN IF NOT EXISTS notas              TEXT;
ALTER TABLE suscripcion ADD COLUMN IF NOT EXISTS creado_en          TIMESTAMP WITH TIME ZONE DEFAULT NOW();
ALTER TABLE suscripcion ADD COLUMN IF NOT EXISTS actualizado_en     TIMESTAMP WITH TIME ZONE DEFAULT NOW();

-- Índices (idempotentes), incluido el del snapshot y el único parcial anti-doble-cobro.
CREATE INDEX IF NOT EXISTS idx_susc_emisor         ON suscripcion(emisor_id, vence);
CREATE INDEX IF NOT EXISTS idx_susc_estado         ON suscripcion(estado, vence);
CREATE INDEX IF NOT EXISTS idx_susc_factura_estado ON suscripcion(factura_estado);
CREATE UNIQUE INDEX IF NOT EXISTS ux_susc_pagook_pago
  ON suscripcion(pagook_pago_id) WHERE pagook_pago_id IS NOT NULL;

-- Verificación: lista las columnas resultantes (deben ser 19).
-- SELECT column_name FROM information_schema.columns
-- WHERE table_name = 'suscripcion' ORDER BY ordinal_position;
