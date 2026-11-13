-- SQL schema for facturalo.pro (Postgres)

-- Requires extension: uuid-ossp
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

CREATE TABLE IF NOT EXISTS emisor (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    ruc VARCHAR(11) NOT NULL UNIQUE,
    razon_social VARCHAR(255) NOT NULL,
    nombre_comercial VARCHAR(255),
    direccion TEXT,
    creado_en TIMESTAMPTZ NOT NULL DEFAULT now(),
    actualizado_en TIMESTAMPTZ,
    activo BOOLEAN NOT NULL DEFAULT TRUE,
    config_json JSONB
);

CREATE TABLE IF NOT EXISTS certificado (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    emisor_id UUID NOT NULL REFERENCES emisor(id) ON DELETE CASCADE,
    pfx_encriptado BYTEA NOT NULL,
    password_encriptado BYTEA NOT NULL,
    serial_number VARCHAR(255),
    fecha_vencimiento DATE,
    creado_en TIMESTAMPTZ NOT NULL DEFAULT now(),
    actualizado_en TIMESTAMPTZ,
    activo BOOLEAN NOT NULL DEFAULT TRUE
);

CREATE TABLE IF NOT EXISTS comprobante (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    emisor_id UUID NOT NULL REFERENCES emisor(id) ON DELETE CASCADE,
    tipo_documento VARCHAR(2) NOT NULL,
    serie VARCHAR(4) NOT NULL,
    numero INTEGER NOT NULL,
    numero_formato VARCHAR(16),
    fecha_emision DATE NOT NULL,
    moneda VARCHAR(3) NOT NULL DEFAULT 'PEN',
    monto_base NUMERIC(14,2) NOT NULL DEFAULT 0,
    monto_igv NUMERIC(14,2) NOT NULL DEFAULT 0,
    monto_total NUMERIC(14,2) NOT NULL DEFAULT 0,
    estado VARCHAR(32) NOT NULL DEFAULT 'pendiente',
    enviado_en TIMESTAMPTZ,
    xml BYTEA,
    pdf BYTEA,
    creado_en TIMESTAMPTZ NOT NULL DEFAULT now(),
    actualizado_en TIMESTAMPTZ,
    creado_por VARCHAR(255)
);

-- Ensure uniqueness per emisor for serie+numero+tipo
CREATE UNIQUE INDEX IF NOT EXISTS uq_comprobante_emisor_tipo_serie_numero ON comprobante (emisor_id, tipo_documento, serie, numero);

CREATE TABLE IF NOT EXISTS linea_detalle (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    comprobante_id UUID NOT NULL REFERENCES comprobante(id) ON DELETE CASCADE,
    orden INTEGER NOT NULL,
    cantidad NUMERIC(12,2) NOT NULL,
    unidad VARCHAR(32),
    descripcion TEXT,
    precio_unitario NUMERIC(14,2) NOT NULL,
    monto_linea NUMERIC(14,2) NOT NULL,
    tributos_json JSONB,
    creado_en TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_comprobante_emisor_fecha ON comprobante (emisor_id, fecha_emision);
CREATE INDEX IF NOT EXISTS idx_comprobante_estado ON comprobante (estado);
CREATE INDEX IF NOT EXISTS idx_linea_comprobante ON linea_detalle (comprobante_id);

CREATE TABLE IF NOT EXISTS respuesta_sunat (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    comprobante_id UUID NOT NULL REFERENCES comprobante(id) ON DELETE CASCADE,
    codigo_cdr VARCHAR(32),
    descripcion TEXT,
    cdr_xml BYTEA,
    recibido_en TIMESTAMPTZ NOT NULL DEFAULT now(),
    hash_documento VARCHAR(255)
);

CREATE TABLE IF NOT EXISTS log_envio (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    comprobante_id UUID,
    emisor_id UUID,
    evento VARCHAR(128),
    nivel VARCHAR(16),
    mensaje TEXT,
    meta_json JSONB,
    creado_en TIMESTAMPTZ NOT NULL DEFAULT now()
);
