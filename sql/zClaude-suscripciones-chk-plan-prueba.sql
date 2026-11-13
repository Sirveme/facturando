-- ════════════════════════════════════════════════════════════════════════════
-- TEMPORAL — Prueba de fuego S/4: permitir plan 'prueba' en el CHECK chk_susc_plan.
-- Correr en PGAdmin ANTES del deploy de la prueba. Reejecutable (DROP IF EXISTS).
--
-- Al terminar la prueba de fuego y quitar el plan 'prueba' del código, revertir con:
--   ALTER TABLE suscripcion DROP CONSTRAINT IF EXISTS chk_susc_plan;
--   ALTER TABLE suscripcion ADD CONSTRAINT chk_susc_plan
--     CHECK (plan IN ('emprendedor','negocio'));
-- ════════════════════════════════════════════════════════════════════════════

ALTER TABLE suscripcion DROP CONSTRAINT IF EXISTS chk_susc_plan;
ALTER TABLE suscripcion ADD CONSTRAINT chk_susc_plan
  CHECK (plan IN ('emprendedor','negocio','prueba'));
