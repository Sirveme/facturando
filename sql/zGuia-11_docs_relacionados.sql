-- =====================================================================
-- zGuia-11 · FASE 1.1 — Documentos relacionados de la GRE (trazabilidad)
-- Ejecutar EN PGAdmin (NO se ejecuta desde la app, NO Alembic).
-- Catálogo de documentos relacionados:
--   01 Factura · 09 Guía remitente · 50 DAM · 04 Liquidación de compra · 99 Otros
-- =====================================================================

CREATE TABLE IF NOT EXISTS guias_remision_docs_relacionados (
    id              VARCHAR(36)  PRIMARY KEY,
    guia_id         VARCHAR(36)  NOT NULL
                     REFERENCES guias_remision(id) ON DELETE CASCADE,
    orden           INTEGER      NOT NULL DEFAULT 1,
    tipo_doc        VARCHAR(2)   NOT NULL,        -- 01 / 09 / 50 / 04 / 99
    descripcion     VARCHAR(255),                 -- obligatorio si tipo_doc = 99
    numero          VARCHAR(50)  NOT NULL,
    emisor_doc_ruc  VARCHAR(11)                   -- RUC del emisor del documento (opcional)
);

CREATE INDEX IF NOT EXISTS idx_gre_docs_rel_guia
    ON guias_remision_docs_relacionados (guia_id);
