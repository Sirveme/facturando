-- ════════════════════════════════════════════════════════════════════════════
-- Central de suscripciones — soporte del motor DB-driven.
-- Correr en PGAdmin ANTES del deploy del refactor. Reejecutable.
--
-- 1) Quitar el CHECK fijo de `plan`: la validez del plan ahora la da susc_plan
--    (FK plan_id). El CHECK bloqueaba 'crece','pro', etc. Reemplaza al temporal
--    sql/zClaude-suscripciones-chk-plan-prueba.sql (ya obsoleto).
-- 2) Flag `publico` en susc_plan: el formulario público solo lista planes
--    publicables; los internos (p.ej. 'prueba') se invocan por parámetro.
-- 3) Plan 'prueba' interno S/4 (activo, NO público) para CADA producto → probar
--    el cobro de cualquiera sin tocar código.
-- ════════════════════════════════════════════════════════════════════════════

-- 1) CHECK obsoleto
ALTER TABLE suscripcion DROP CONSTRAINT IF EXISTS chk_susc_plan;

-- 2) Flag publico (default TRUE → los planes existentes quedan publicables)
ALTER TABLE susc_plan ADD COLUMN IF NOT EXISTS publico BOOLEAN NOT NULL DEFAULT TRUE;

-- 3) Plan 'prueba' interno (S/4, activo, NO público) en TODOS los productos
INSERT INTO susc_plan (producto_id, codigo, nombre, precio_mensual, precio_anual, activo, publico, orden)
SELECT p.id, 'prueba', 'Prueba interna', 4.00, 4.00, TRUE, FALSE, 99
FROM susc_producto p
ON CONFLICT (producto_id, codigo) DO NOTHING;

-- Verificación (opcional):
--   SELECT pr.codigo producto, pl.codigo plan, pl.precio_mensual, pl.activo, pl.publico
--     FROM susc_plan pl JOIN susc_producto pr ON pr.id=pl.producto_id ORDER BY 1,2;
