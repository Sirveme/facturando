-- ════════════════════════════════════════════════════════════════════════════
-- Central de suscripciones — descripciones para el formulario dinámico + upsell.
-- Aditivo, reejecutable. Correr en PGAdmin ANTES del deploy del formulario dinámico.
-- Los textos son de arranque (decentes); Duilio los refina luego en PGAdmin.
-- ════════════════════════════════════════════════════════════════════════════

ALTER TABLE susc_producto ADD COLUMN IF NOT EXISTS descripcion VARCHAR(255);  -- gancho upsell
ALTER TABLE susc_plan     ADD COLUMN IF NOT EXISTS descripcion VARCHAR(255);  -- subtítulo tarjeta

-- Descripciones de producto (upsell)
UPDATE susc_producto SET descripcion = 'Facturación electrónica SUNAT en segundos'            WHERE codigo = 'facturalo';
UPDATE susc_producto SET descripcion = 'Punto de venta con voz para tu negocio'               WHERE codigo = 'quevendi';
UPDATE susc_producto SET descripcion = 'Sistema completo para restaurantes y chifas'          WHERE codigo = 'metraes';
UPDATE susc_producto SET descripcion = 'Monitoreo de tu buzón SUNAT, evita multas por no enterarte' WHERE codigo = 'alerta';
UPDATE susc_producto SET descripcion = 'Confirma tus cobros Yape/Plin automáticamente'        WHERE codigo = 'pagook';

-- Subtítulos de planes públicos (arranque; refinar luego)
UPDATE susc_plan pl SET descripcion = '1 RUC · Comprobantes ilimitados'
  FROM susc_producto pr WHERE pr.id = pl.producto_id AND pr.codigo='facturalo' AND pl.codigo='emprendedor';
UPDATE susc_plan pl SET descripcion = '3 RUCs · Comprobantes ilimitados'
  FROM susc_producto pr WHERE pr.id = pl.producto_id AND pr.codigo='facturalo' AND pl.codigo='negocio';
UPDATE susc_plan pl SET descripcion = 'Punto de venta + inventario'
  FROM susc_producto pr WHERE pr.id = pl.producto_id AND pr.codigo='quevendi' AND pl.codigo='crece';
UPDATE susc_plan pl SET descripcion = 'Todo Crece + reportes avanzados'
  FROM susc_producto pr WHERE pr.id = pl.producto_id AND pr.codigo='quevendi' AND pl.codigo='pro';

-- Verificación (opcional):
--   SELECT codigo, descripcion FROM susc_producto ORDER BY codigo;
--   SELECT pr.codigo producto, pl.codigo plan, pl.descripcion
--     FROM susc_plan pl JOIN susc_producto pr ON pr.id=pl.producto_id
--     WHERE pl.publico ORDER BY 1,2;
