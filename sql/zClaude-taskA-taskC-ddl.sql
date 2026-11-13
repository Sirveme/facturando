-- ============================================================================
-- zClaude-taskA-taskC-ddl.sql
-- DDL para Task A (validación de receptor) + Task C (compartir/descargar).
--
-- ⚠️ ORDEN OBLIGATORIO: correr ESTE SQL en PGAdmin ANTES de desplegar el código
-- del Deploy 2. Al agregar columnas al modelo, TODO SELECT de `comprobante` las
-- incluye; si el código sale antes que las columnas, se cae CUALQUIER lectura de
-- comprobantes (dashboard, consultas, emisión). Primero esto; luego el deploy.
--
-- Ambas columnas son aditivas y nullable; no reescriben datos existentes.
-- ============================================================================

SET lock_timeout = '3s';

BEGIN;

-- Task A: marca de receptor NO validado contra padrón (fail-open). NULL = validado/no aplica.
ALTER TABLE comprobante
    ADD COLUMN IF NOT EXISTS receptor_no_validado boolean;

-- Task C: token aleatorio no adivinable para la página pública /c/{token}.
ALTER TABLE comprobante
    ADD COLUMN IF NOT EXISTS share_token varchar(64);

-- Unicidad del token (Postgres permite múltiples NULL en un índice UNIQUE).
CREATE UNIQUE INDEX IF NOT EXISTS ux_comprobante_share_token
    ON comprobante (share_token);

COMMIT;

-- Verificación (debe listar las 2 columnas):
-- SELECT column_name, data_type, is_nullable
--   FROM information_schema.columns
--  WHERE table_name = 'comprobante'
--    AND column_name IN ('receptor_no_validado', 'share_token');
