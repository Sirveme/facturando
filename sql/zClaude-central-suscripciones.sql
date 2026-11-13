-- ════════════════════════════════════════════════════════════════════════════
-- CENTRAL MÍNIMO DE SUSCRIPCIONES (Facturalo × ecosistema PSP)
-- Tablas NUEVAS + extensión ADITIVA de `suscripcion`. No toca emisión ni stock.
--
-- OJO: la tabla `producto` YA EXISTE (inventario/SKU) → el central usa `susc_*`.
--
-- ORDEN (respétalo): 1) crear tablas → A) columnas nullable en suscripcion →
-- SEED productos/planes/inclusiones → B) backfill → C) NOT NULL + FK + índices.
-- Correr COMPLETO en PGAdmin ANTES del deploy. Reejecutable (IF NOT EXISTS / DO guards).
-- ════════════════════════════════════════════════════════════════════════════

-- gen_random_uuid() requiere Postgres 13+ (en <13, descomenta la extensión):
-- CREATE EXTENSION IF NOT EXISTS pgcrypto;

-- ─────────────────────────────────────────────────────────────────────────────
-- 1) TABLAS DEL CENTRAL
-- ─────────────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS susc_producto (
  id            VARCHAR(36) PRIMARY KEY DEFAULT gen_random_uuid(),
  codigo        VARCHAR(30)  NOT NULL UNIQUE,     -- facturalo|quevendi|metraes|alerta|pagook
  nombre        VARCHAR(100) NOT NULL,
  serie_factura VARCHAR(4)   NOT NULL UNIQUE,     -- FF50/FQ50/FM50/FA50/FP50
  activo        BOOLEAN      NOT NULL DEFAULT TRUE,
  creado_en     TIMESTAMPTZ  DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS susc_plan (
  id             VARCHAR(36) PRIMARY KEY DEFAULT gen_random_uuid(),
  producto_id    VARCHAR(36) NOT NULL REFERENCES susc_producto(id),
  codigo         VARCHAR(40) NOT NULL,
  nombre         VARCHAR(100) NOT NULL,
  precio_mensual NUMERIC(10,2) NOT NULL,
  precio_anual   NUMERIC(10,2) NOT NULL,
  activo         BOOLEAN NOT NULL DEFAULT TRUE,
  orden          INTEGER DEFAULT 0,
  creado_en      TIMESTAMPTZ DEFAULT NOW(),
  CONSTRAINT uq_susc_plan UNIQUE (producto_id, codigo)
);

-- Qué productos INCLUYE un plan (ej. QueVendi incluye Facturalo gratis)
CREATE TABLE IF NOT EXISTS susc_plan_incluye (
  id                   VARCHAR(36) PRIMARY KEY DEFAULT gen_random_uuid(),
  plan_id              VARCHAR(36) NOT NULL REFERENCES susc_plan(id),
  producto_incluido_id VARCHAR(36) NOT NULL REFERENCES susc_producto(id),
  tipo_precio_incluido VARCHAR(12) NOT NULL
      CHECK (tipo_precio_incluido IN ('gratis','porcentaje','monto_fijo')),
  valor_incluido       NUMERIC(10,2) NOT NULL DEFAULT 0,  -- gratis→0; porcentaje→50.00; monto_fijo→25.00
  creado_en            TIMESTAMPTZ DEFAULT NOW(),
  CONSTRAINT uq_susc_plan_incluye UNIQUE (plan_id, producto_incluido_id)
);

-- Features/límites por plan (CREADA, sin uso aún)
CREATE TABLE IF NOT EXISTS susc_feature (
  id        VARCHAR(36) PRIMARY KEY DEFAULT gen_random_uuid(),
  plan_id   VARCHAR(36) NOT NULL REFERENCES susc_plan(id),
  clave     VARCHAR(60) NOT NULL,
  tipo      VARCHAR(10) NOT NULL CHECK (tipo IN ('limite','booleano','texto')),
  valor     VARCHAR(255),
  creado_en TIMESTAMPTZ DEFAULT NOW(),
  CONSTRAINT uq_susc_feature UNIQUE (plan_id, clave)
);

-- ─────────────────────────────────────────────────────────────────────────────
-- A) EXTENDER suscripcion — columnas NUEVAS en NULLABLE (no rompe filas existentes)
--    emisor_id = principal (ya existe, NOT NULL). cliente_ruc = denormalizado:
--    identifica al suscriptor aunque un producto futuro tenga clientes que NO son
--    emisores de Facturalo.
-- ─────────────────────────────────────────────────────────────────────────────
ALTER TABLE suscripcion ADD COLUMN IF NOT EXISTS producto_id VARCHAR(36);
ALTER TABLE suscripcion ADD COLUMN IF NOT EXISTS plan_id     VARCHAR(36);
ALTER TABLE suscripcion ADD COLUMN IF NOT EXISTS cliente_ruc VARCHAR(15);

-- ─────────────────────────────────────────────────────────────────────────────
-- SEED — productos, planes e inclusiones
-- ─────────────────────────────────────────────────────────────────────────────
INSERT INTO susc_producto (codigo, nombre, serie_factura) VALUES
  ('facturalo','Facturalo','FF50'),
  ('quevendi','QueVendi','FQ50'),
  ('metraes','Metraes','FM50'),
  ('alerta','Alerta','FA50'),
  ('pagook','PagoOK','FP50')
ON CONFLICT (codigo) DO NOTHING;

-- Planes Facturalo
INSERT INTO susc_plan (producto_id, codigo, nombre, precio_mensual, precio_anual, orden)
SELECT p.id, v.codigo, v.nombre, v.pm, v.pa, v.orden
FROM susc_producto p
JOIN (VALUES
  ('emprendedor','Emprendedor',29.00,290.00,1),
  ('negocio','Negocio',55.00,550.00,2)
) AS v(codigo,nombre,pm,pa,orden) ON TRUE
WHERE p.codigo='facturalo'
ON CONFLICT (producto_id, codigo) DO NOTHING;

-- Planes QueVendi (solo Crece y Pro; anual = mensual×10 — "paga 10 usa 12")
INSERT INTO susc_plan (producto_id, codigo, nombre, precio_mensual, precio_anual, orden)
SELECT p.id, v.codigo, v.nombre, v.pm, v.pa, v.orden
FROM susc_producto p
JOIN (VALUES
  ('crece','Crece',79.00,790.00,1),
  ('pro','Pro',119.00,1190.00,2)
) AS v(codigo,nombre,pm,pa,orden) ON TRUE
WHERE p.codigo='quevendi'
ON CONFLICT (producto_id, codigo) DO NOTHING;

-- Inclusiones: QueVendi y Metraes (TODOS sus planes) → incluyen Facturalo GRATIS.
-- (Metraes aún no tiene planes → no inserta nada hasta que los definas; es correcto.)
INSERT INTO susc_plan_incluye (plan_id, producto_incluido_id, tipo_precio_incluido, valor_incluido)
SELECT pl.id, fac.id, 'gratis', 0
FROM susc_plan pl
JOIN susc_producto pr  ON pr.id = pl.producto_id AND pr.codigo IN ('quevendi','metraes')
JOIN susc_producto fac ON fac.codigo = 'facturalo'
ON CONFLICT (plan_id, producto_incluido_id) DO NOTHING;

-- ─────────────────────────────────────────────────────────────────────────────
-- B) BACKFILL de filas existentes (hoy: la FF50-1 de prueba) → Facturalo + su RUC
-- ─────────────────────────────────────────────────────────────────────────────
UPDATE suscripcion
   SET producto_id = (SELECT id FROM susc_producto WHERE codigo = 'facturalo')
 WHERE producto_id IS NULL;

UPDATE suscripcion s
   SET cliente_ruc = e.ruc
  FROM emisor e
 WHERE e.id = s.emisor_id
   AND s.cliente_ruc IS NULL;

-- ─────────────────────────────────────────────────────────────────────────────
-- C) Ya sin NULLs → NOT NULL + FKs + índices
-- ─────────────────────────────────────────────────────────────────────────────
ALTER TABLE suscripcion ALTER COLUMN producto_id SET NOT NULL;
ALTER TABLE suscripcion ALTER COLUMN cliente_ruc SET NOT NULL;
-- plan_id queda NULLABLE a propósito (la FF50-1 'prueba' no tiene fila en susc_plan).

DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'fk_susc_producto') THEN
    ALTER TABLE suscripcion ADD CONSTRAINT fk_susc_producto
      FOREIGN KEY (producto_id) REFERENCES susc_producto(id);
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'fk_susc_plan') THEN
    ALTER TABLE suscripcion ADD CONSTRAINT fk_susc_plan
      FOREIGN KEY (plan_id) REFERENCES susc_plan(id);
  END IF;
END $$;

CREATE INDEX IF NOT EXISTS idx_susc_emisor_producto  ON suscripcion(emisor_id, producto_id);
CREATE INDEX IF NOT EXISTS idx_susc_rucprod          ON suscripcion(cliente_ruc, producto_id);
-- idx_susc_estado (estado, vence) ya existe del DDL base.

-- ════════════════════════════════════════════════════════════════════════════
-- Verificación rápida (opcional, read-only):
--   SELECT codigo, serie_factura FROM susc_producto ORDER BY codigo;
--   SELECT pr.codigo producto, pl.codigo plan, pl.precio_mensual, pl.precio_anual
--     FROM susc_plan pl JOIN susc_producto pr ON pr.id=pl.producto_id ORDER BY 1,2;
--   SELECT pr.codigo plan_de, inc.codigo incluye, i.tipo_precio_incluido
--     FROM susc_plan_incluye i
--     JOIN susc_plan pl ON pl.id=i.plan_id JOIN susc_producto pr ON pr.id=pl.producto_id
--     JOIN susc_producto inc ON inc.id=i.producto_incluido_id;
--   SELECT id, emisor_id, cliente_ruc, producto_id, plan_id, plan, estado FROM suscripcion;
-- ════════════════════════════════════════════════════════════════════════════
