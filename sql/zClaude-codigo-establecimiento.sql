-- Código de establecimiento anexo (SUNAT AddressTypeCode) opcional por comprobante.
-- Aditivo, nullable. Correr en PGAdmin ANTES del deploy. Reejecutable.
-- Si queda NULL, el XML usa el default del emisor (config_json.codigo_establecimiento) o '0000'.
--
-- lock_timeout: si no obtiene el ACCESS EXCLUSIVE en 3s (hay una transacción larga tomando
-- la tabla), FALLA de inmediato en vez de bloquear la facturación. Reintentar luego.
SET lock_timeout = '3s';
ALTER TABLE comprobante ADD COLUMN IF NOT EXISTS codigo_establecimiento VARCHAR(4);
