-- ============================================================================
-- zClaude-4094-direcciones-emisor.sql
-- Corrige el domicilio fiscal del emisor en "-" que dispara la observación SUNAT
-- 4094. En el XML, la línea de dirección del emisor es `emisor.direccion or '-'`
-- (xml_generator.py:607); si está NULL/vacía emite "-" → 4094.
--
-- Solo toca `emisor.direccion` (y `ubigeo` cuando se conoce) de RUCs puntuales, y
-- SOLO si hoy están NULL/''/'-' (idempotente; no pisa datos ya cargados).
-- Correr en PGAdmin. NO cambia nada de emisión ni de comprobantes ya emitidos.
--
-- lock_timeout corto: si la fila está bloqueada, aborta en vez de esperar.
-- ============================================================================

SET lock_timeout = '3s';

BEGIN;

-- ─────────────────────────────────────────────────────────────────────────────
-- 1) MACRO INVERSIONES TECNOLOGICAS AURORA S.A.C. — RUC 20616219686
--    Dirección CONFIRMADA del padrón (apis.net.pe), ubigeo 150122 (Lima/Lima/Miraflores).
-- ─────────────────────────────────────────────────────────────────────────────
UPDATE emisor
   SET direccion = 'AV. MONSEÑOR ROCA Y BOLOGNA NRO 940 INT. A DEP. 102 URB. PROLONGACION AURORA',
       ubigeo    = COALESCE(NULLIF(ubigeo, ''), '150122')
 WHERE ruc = '20616219686'
   AND (direccion IS NULL OR btrim(direccion) IN ('', '-'));

-- ─────────────────────────────────────────────────────────────────────────────
-- 2) Rest Gourmet / TTITO HUAMANI SARA — RUC 10467016283 (persona natural)
--    Domicilio fiscal (anexo 0000) provisto por Duilio: Calle Ramires Hurtado 1211,
--    Belén, Maynas, Loreto. Ubigeo 160112 (Belén/Maynas/Loreto) — consistente con el
--    estándar; PENDIENTE confirmar en vivo con el lookup de PSP cuando PSP_API_KEY esté
--    en Railway (no pude consultarlo localmente: la key aún no existe para Facturalo).
--    apis.net.pe no devuelve dirección para este RUC (persona natural).
UPDATE emisor
   SET direccion = 'CALLE RAMIRES HURTADO 1211, BELEN, MAYNAS, LORETO',
       ubigeo    = COALESCE(NULLIF(ubigeo, ''), '160112')
 WHERE ruc = '10467016283'
   AND (direccion IS NULL OR btrim(direccion) IN ('', '-'));

COMMIT;

-- Verificación:
-- SELECT ruc, direccion, ubigeo FROM emisor WHERE ruc IN ('20616219686','10467016283');
