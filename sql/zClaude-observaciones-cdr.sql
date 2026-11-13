SET lock_timeout = '3s';

-- Observaciones SUNAT (notas 4xxx) en la respuesta del CDR. Aditivo, nullable.
-- Guarda una lista JSON [{"codigo":"4xxx","descripcion":"..."}] cuando el CDR es
-- 'aceptado con observaciones'. Correr en PGAdmin ANTES de desplegar el código.
-- lock_timeout (arriba): si no obtiene el lock en 3s (hay transacción larga sobre la
-- tabla), FALLA de inmediato en vez de bloquear. Reejecutable (IF NOT EXISTS).
ALTER TABLE respuesta_sunat ADD COLUMN IF NOT EXISTS observaciones JSONB;

-- Verificación (debe devolver 1 fila):
-- SELECT column_name, data_type FROM information_schema.columns
--   WHERE table_name = 'respuesta_sunat' AND column_name = 'observaciones';
