import uuid
from uuid import uuid4
from datetime import datetime, timezone, date, timedelta
from decimal import Decimal
from sqlalchemy import (
    Column, String, Integer, Boolean, Date, DateTime, Text, Numeric, LargeBinary, JSON, ForeignKey, Index
)
from sqlalchemy.orm import relationship, declarative_base

Base = declarative_base()

def gen_uuid():
    return str(uuid.uuid4())

def utc_now():
    """Retorna datetime actual en UTC"""
    return datetime.now(timezone.utc)

class Emisor(Base):
    __tablename__ = 'emisor'

    id = Column(String(36), primary_key=True, default=gen_uuid)
    ruc = Column(String(11), nullable=False, unique=True)
    razon_social = Column(String(255), nullable=False)
    nombre_comercial = Column(String(255))
    direccion = Column(Text)
    ubigeo = Column(String, nullable=True)
    sol_usuario = Column(String(128))
    sol_password = Column(String(255))
    creado_en = Column(DateTime, default=utc_now)
    actualizado_en = Column(DateTime)
    activo = Column(Boolean, default=True)
    config_json = Column(JSON)
    lema = Column(String(200))
    establecimiento_anexo = Column(String(200))
    es_agente_retencion = Column(Boolean, default=False)
    es_agente_percepcion = Column(Boolean, default=False)
    logo_url = Column(String(500))
    color_primario = Column(String(7), default='#2c3e50')
    color_secundario = Column(String(7), default='#e74c3c')
    telefono = Column(String(20))
    web = Column(String(200))
    formato_factura = Column(String(10), default='A4')
    formato_boleta = Column(String(10), default='A4')
    formato_ticket = Column(String(10), default='TICKET')
    formato_nc_nd = Column(String(10), default='A4')
    produccion = Column(Boolean, default=False, nullable=False)

    # GRE - Guía de Remisión Electrónica (API REST OAuth2)
    gre_client_id = Column(String, nullable=True)
    gre_client_secret_encrypted = Column(String, nullable=True)  # cifrado igual que sol_password (Fernet)
    gre_serie = Column(String, default='T060')
    gre_correlativo = Column(Integer, default=0)
    gre_sol_usuario = Column(String, nullable=True)  # NULL = usar sol_usuario

    # API
    api_key = Column(String(64), unique=True)
    api_secret = Column(String(64))
    api_activa = Column(Boolean, default=False)
    plan = Column(String(50), default='free')
    docs_mes_limite = Column(Integer, default=50)
    docs_mes_usados = Column(Integer, default=0)
    fecha_reset_contador = Column(Date, default=date.today)

    # Autenticación
    email = Column(String(255), unique=True)
    password_hash = Column(String(255))
    nombre_contacto = Column(String(255))
    telefono = Column(String(20))
    trial_inicio = Column(DateTime)
    trial_fin = Column(DateTime)
    modo_test = Column(Boolean, default=True)
    activo = Column(Boolean, default=True)

    certificados = relationship('Certificado', back_populates='emisor', cascade='all, delete-orphan')
    comprobantes = relationship('Comprobante', back_populates='emisor', cascade='all, delete-orphan')
    clientes = relationship('Cliente', back_populates='emisor', cascade='all, delete-orphan')
    productos = relationship('Producto', back_populates='emisor', cascade='all, delete-orphan')
    usuarios = relationship('Usuario', back_populates='emisor', cascade='all, delete-orphan')
    establecimientos = relationship('Establecimiento', back_populates='emisor', cascade='all, delete-orphan')
    categorias = relationship("Categoria", back_populates="emisor")
    productos = relationship("Producto", back_populates="emisor")

    logo = Column(LargeBinary, nullable=True)
    logo_content_type = Column(String(50), nullable=True)

class Certificado(Base):
    __tablename__ = 'certificado'

    id = Column(String(36), primary_key=True, default=gen_uuid)
    emisor_id = Column(String(36), ForeignKey('emisor.id'), nullable=False)
    pfx_encriptado = Column(LargeBinary, nullable=False)
    password_encriptado = Column(LargeBinary, nullable=False)
    serial_number = Column(String(255))
    fecha_vencimiento = Column(Date)
    creado_en = Column(DateTime, default=utc_now)
    actualizado_en = Column(DateTime)
    activo = Column(Boolean, default=True)

    emisor = relationship('Emisor', back_populates='certificados')

class Comprobante(Base):
    __tablename__ = 'comprobante'

    id = Column(String(36), primary_key=True, default=gen_uuid)
    emisor_id = Column(String(36), ForeignKey('emisor.id'), nullable=False)
    tipo_documento = Column(String(2), nullable=False)
    serie = Column(String(4), nullable=False)
    numero = Column(Integer, nullable=False)
    numero_formato = Column(String(16))
    fecha_emision = Column(Date, nullable=False)
    moneda = Column(String(3), default='PEN')
    forma_pago = Column(String(20), default='Contado')
    monto_base = Column(Numeric(14,2), default=Decimal('0.00'))
    monto_igv = Column(Numeric(14,2), default=Decimal('0.00'))
    monto_total = Column(Numeric(14,2), default=Decimal('0.00'))
    op_gravada = Column(Numeric(14,2), default=Decimal('0.00'))
    op_exonerada = Column(Numeric(14,2), default=Decimal('0.00'))
    op_inafecta = Column(Numeric(14,2), default=Decimal('0.00'))
    estado = Column(String(32), default='pendiente')
    enviado_en = Column(DateTime)
    xml = Column(LargeBinary)
    pdf = Column(LargeBinary)
    creado_en = Column(DateTime, default=utc_now)
    actualizado_en = Column(DateTime)
    creado_por = Column(String(255))
    observaciones = Column(Text)
    cliente_id = Column(String, ForeignKey('cliente.id'))
    intentos_envio = Column(Integer, default=0)
    ultimo_intento_envio = Column(DateTime)
    procesando_desde = Column(DateTime)
    cliente_tipo_documento = Column(String(1))
    cliente_numero_documento = Column(String(15))
    cliente_razon_social = Column(String(500))
    cliente_direccion = Column(String(500))
    cliente_departamento = Column(String(100))
    cliente_provincia = Column(String(100))
    cliente_distrito = Column(String(100))
    cliente_ubigeo = Column(String(6))
    doc_referencia_tipo = Column(String(2))      # Tipo doc referencia (01, 03)
    doc_referencia_numero = Column(String(20))   # Número del doc referencia
    motivo_nota = Column(String(2))              # Motivo NC/ND (01-07)
    referencia_externa = Column(String(100), index=True)
    tipo_documento = Column(String(2), nullable=False)
    tipo_operacion = Column(String(4), default='0101')  # 0101=Venta interna
    hash_cpe = Column(String(100), nullable=True)

    emisor = relationship('Emisor', back_populates='comprobantes')
    lineas = relationship('LineaDetalle', back_populates='comprobante', cascade='all, delete-orphan')
    respuesta = relationship('RespuestaSunat', uselist=False, back_populates='comprobante', cascade='all, delete-orphan')
    cliente = relationship("Cliente", back_populates="comprobantes")

class LineaDetalle(Base):
    __tablename__ = 'linea_detalle'

    id = Column(String(36), primary_key=True, default=gen_uuid)
    comprobante_id = Column(String(36), ForeignKey('comprobante.id'), nullable=False)
    orden = Column(Integer, nullable=False)
    cantidad = Column(Numeric(12,2), nullable=False)
    unidad = Column(String(32))
    descripcion = Column(Text)
    precio_unitario = Column(Numeric(14,2), nullable=False)
    valor_unitario = Column(Numeric(14,2))
    descuento = Column(Numeric(14,2), default=Decimal('0.00'))
    subtotal = Column(Numeric(14,2))
    igv = Column(Numeric(14,2))
    codigo = Column(String(50))
    monto_linea = Column(Numeric(14,2), nullable=False)
    tributos_json = Column(JSON)
    creado_en = Column(DateTime, default=utc_now)
    tipo_afectacion_igv = Column(String(2), default='10')
    es_bonificacion = Column(Boolean, default=False)

    comprobante = relationship('Comprobante', back_populates='lineas')

class RespuestaSunat(Base):
    __tablename__ = 'respuesta_sunat'

    id = Column(String(36), primary_key=True, default=gen_uuid)
    comprobante_id = Column(String(36), ForeignKey('comprobante.id'), nullable=False)
    codigo_cdr = Column(String(32))
    descripcion = Column(Text)
    cdr_xml = Column(LargeBinary)
    recibido_en = Column(DateTime, default=utc_now)
    hash_documento = Column(String(255))

    comprobante = relationship('Comprobante', back_populates='respuesta')

class LogEnvio(Base):
    __tablename__ = 'log_envio'

    id = Column(String(36), primary_key=True, default=gen_uuid)
    comprobante_id = Column(String(36))
    emisor_id = Column(String(36))
    evento = Column(String(128))
    nivel = Column(String(16))
    mensaje = Column(Text)
    meta_json = Column(JSON)
    creado_en = Column(DateTime, default=utc_now)


# ========================================
# GESTIÓN DE CLIENTES
# ========================================

class Cliente(Base):
    __tablename__ = 'cliente'
    
    id = Column(String, primary_key=True, default=gen_uuid)
    emisor_id = Column(String, ForeignKey('emisor.id'), nullable=False)
    
    # Identificación
    tipo_documento = Column(String(1), nullable=False)  # '6' RUC, '1' DNI, '4' CE
    numero_documento = Column(String(11), nullable=False)
    razon_social = Column(String(500), nullable=False)
    nombre_comercial = Column(String(500))
    
    # Dirección
    direccion = Column(String(500))
    ubigeo = Column(String(6))  # Código SUNAT
    departamento = Column(String(100))
    provincia = Column(String(100))
    distrito = Column(String(100))
    urbanizacion = Column(String(200))
    codigo_postal = Column(String(10))
    
    # Contacto
    email = Column(String(200))
    telefono = Column(String(20))
    celular = Column(String(20))
    
    # Representante Legal (para facturas)
    representante_nombre = Column(String(200))
    representante_dni = Column(String(8))
    representante_cargo = Column(String(100))
    
    # Comercial
    condicion_pago = Column(String(20), default='contado')  # 'contado', 'credito'
    credito_dias = Column(Integer, default=0)
    descuento_porcentaje = Column(Numeric(5,2), default=0)
    limite_credito = Column(Numeric(12,2))
    
    # Control
    estado_sunat = Column(String(20))  # 'ACTIVO', 'BAJA', etc.
    condicion_sunat = Column(String(20))  # 'HABIDO', 'NO HABIDO'
    
    # Metadata
    notas = Column(Text)
    activo = Column(Boolean, default=True)
    creado_en = Column(DateTime, default=utc_now)
    actualizado_en = Column(DateTime, default=utc_now, onupdate=utc_now)
    
    # Relaciones
    emisor = relationship("Emisor", back_populates="clientes")
    comprobantes = relationship("Comprobante", back_populates="cliente")
    
    # Índices
    __table_args__ = (
        Index('idx_cliente_emisor_documento', 'emisor_id', 'numero_documento'),
        Index('idx_cliente_razon_social', 'razon_social'),
    )


# ========================================
# CATÁLOGO DE PRODUCTOS/SERVICIOS
# ========================================

class Producto(Base):
    __tablename__ = 'producto'
    
    id = Column(String, primary_key=True, default=gen_uuid)
    emisor_id = Column(String, ForeignKey('emisor.id'), nullable=False)
    
    # Identificación
    codigo_interno = Column(String(50), nullable=False)  # SKU
    codigo_sunat = Column(String(50))  # Código catálogo SUNAT
    codigo_barras = Column(String(50))
    
    # Descripción
    descripcion = Column(String(500), nullable=False)
    descripcion_corta = Column(String(200))
    
    # Clasificación
    categoria = Column(String(100))
    subcategoria = Column(String(100))
    marca = Column(String(100))
    modelo = Column(String(100))
    
    # Unidad SUNAT
    unidad_medida = Column(String(3), default='NIU')  # NIU, ZZ, KGM, etc.
    
    # Precios
    precio_venta = Column(Numeric(12,4), nullable=False)
    precio_compra = Column(Numeric(12,4))
    moneda = Column(String(3), default='PEN')
    
    # Impuestos
    afecto_igv = Column(Boolean, default=True)
    tipo_afectacion_igv = Column(String(2), default='10')  # Catálogo 07
    
    # Stock (opcional)
    maneja_stock = Column(Boolean, default=False)
    stock_actual = Column(Numeric(12,3), default=0)
    stock_minimo = Column(Numeric(12,3), default=0)
    
    # Control
    activo = Column(Boolean, default=True)
    es_favorito = Column(Boolean, default=False)  # Para acceso rápido
    veces_usado = Column(Integer, default=0)
    
    # Metadata
    creado_en = Column(DateTime, default=utc_now)
    actualizado_en = Column(DateTime, default=utc_now, onupdate=utc_now)
    
    # Relaciones
    emisor = relationship("Emisor", back_populates="productos")
    
    # Índices
    __table_args__ = (
        Index('idx_producto_emisor_codigo', 'emisor_id', 'codigo_interno'),
        Index('idx_producto_descripcion', 'descripcion'),
        Index('idx_producto_favorito', 'emisor_id', 'es_favorito'),
    )


# ========================================
# NOTAS DE CRÉDITO/DÉBITO
# ========================================

class NotaCreditoDebito(Base):
    __tablename__ = 'nota_credito_debito'
    
    id = Column(String, primary_key=True, default=gen_uuid)
    emisor_id = Column(String, ForeignKey('emisor.id'), nullable=False)
    
    # Relación con comprobante original
    comprobante_afectado_id = Column(String, ForeignKey('comprobante.id'), nullable=False)
    tipo_documento_afectado = Column(String(2))  # '01', '03'
    serie_afectada = Column(String(4))
    numero_afectado = Column(Integer)
    
    # Datos de la nota
    tipo_nota = Column(String(2), nullable=False)  # '07' NC, '08' ND
    serie = Column(String(4), nullable=False)
    numero = Column(Integer, nullable=False)
    numero_formato = Column(String(20))  # "FC01-00000125"
    fecha_emision = Column(Date, nullable=False)
    
    # Motivo según catálogo SUNAT
    motivo_codigo = Column(String(2), nullable=False)
    '''
    Catálogo 09 - Notas de Crédito:
    01 - Anulación de la operación
    02 - Anulación por error en el RUC
    03 - Corrección por error en la descripción
    04 - Descuento global
    05 - Descuento por ítem
    06 - Devolución total
    07 - Devolución por ítem
    08 - Bonificación
    09 - Disminución en el valor
    10 - Otros conceptos
    13 - Ajustes afectos al IVAP
    
    Catálogo 10 - Notas de Débito:
    01 - Intereses por mora
    02 - Aumento en el valor
    03 - Penalidades/otros conceptos
    11 - Ajustes de operaciones de exportación
    12 - Ajustes afectos al IVAP
    '''
    motivo_descripcion = Column(Text)
    
    # Montos
    moneda = Column(String(3), default='PEN')
    monto_base = Column(Numeric(12,2), nullable=False)
    monto_igv = Column(Numeric(12,2), nullable=False)
    monto_total = Column(Numeric(12,2), nullable=False)
    
    # Estado SUNAT
    estado = Column(String(20), default='pendiente')
    xml = Column(Text)
    hash_cpe = Column(String(100))
    codigo_qr = Column(Text)
    
    # Respuesta SUNAT
    estado_sunat = Column(String(50))
    codigo_respuesta = Column(String(10))
    descripcion_respuesta = Column(Text)
    cdr_xml = Column(Text)
    fecha_envio_sunat = Column(DateTime)
    
    # Metadata
    observaciones = Column(Text)
    creado_en = Column(DateTime, default=utc_now)
    actualizado_en = Column(DateTime, default=utc_now, onupdate=utc_now)
    
    # Relaciones
    emisor = relationship("Emisor")
    comprobante_afectado = relationship("Comprobante")
    
    # Índices
    __table_args__ = (
        Index('idx_nota_emisor_serie', 'emisor_id', 'serie', 'numero'),
        Index('idx_nota_comprobante_afectado', 'comprobante_afectado_id'),
    )

# ========================================
# USUARIOS (Multi-usuario por emisor)
# ========================================

class Usuario(Base):
    __tablename__ = 'usuario'
    
    id = Column(String, primary_key=True, default=gen_uuid)
    emisor_id = Column(String, ForeignKey('emisor.id'), nullable=False)
    
    # Autenticación
    email = Column(String(200), unique=True, nullable=False)
    password_hash = Column(String(200), nullable=False)
    
    # Datos personales
    nombres = Column(String(200), nullable=False)
    apellidos = Column(String(200))
    dni = Column(String(8))
    telefono = Column(String(20))
    
    # Rol y permisos
    rol = Column(String(50), default='vendedor')
    '''
    Roles:
    - admin: Acceso total, puede gestionar usuarios
    - contador: Emite, anula, reportes completos
    - vendedor: Solo emite facturas/boletas
    - consultor: Solo ve reportes
    - almacenero: Gestiona productos, guías
    '''
    
    # Permisos específicos
    puede_emitir_factura = Column(Boolean, default=True)
    puede_emitir_boleta = Column(Boolean, default=True)
    puede_emitir_nota_credito = Column(Boolean, default=False)
    puede_emitir_guia = Column(Boolean, default=False)
    puede_anular = Column(Boolean, default=False)
    puede_ver_reportes = Column(Boolean, default=False)
    puede_gestionar_clientes = Column(Boolean, default=False)
    puede_gestionar_productos = Column(Boolean, default=False)
    puede_configurar = Column(Boolean, default=False)
    
    # Restricciones
    series_permitidas = Column(JSON)  # ["F001", "B001"] o null para todas
    
    # Control de sesión
    ultimo_login = Column(DateTime)
    token_sesion = Column(String(200))
    sesion_expira = Column(DateTime)
    
    # Estado
    activo = Column(Boolean, default=True)
    email_verificado = Column(Boolean, default=False)
    
    # Metadata
    creado_en = Column(DateTime, default=utc_now)
    actualizado_en = Column(DateTime, default=utc_now, onupdate=utc_now)
    creado_por = Column(String)  # ID del usuario que lo creó
    
    # Relaciones
    emisor = relationship("Emisor", back_populates="usuarios")
    
    # Índices
    __table_args__ = (
        Index('idx_usuario_email', 'email'),
        Index('idx_usuario_emisor', 'emisor_id', 'activo'),
    )


# ========================================
# ESTABLECIMIENTOS ANEXOS
# ========================================

class Establecimiento(Base):
    __tablename__ = 'establecimiento'
    
    id = Column(String, primary_key=True, default=gen_uuid)
    emisor_id = Column(String, ForeignKey('emisor.id'), nullable=False)
    
    # Identificación
    codigo = Column(String(10), nullable=False)  # "0000" principal, "0001", "0002"
    nombre = Column(String(200), nullable=False)
    
    # Dirección del establecimiento
    direccion = Column(String(500), nullable=False)
    ubigeo = Column(String(6), nullable=False)
    departamento = Column(String(100))
    provincia = Column(String(100))
    distrito = Column(String(100))
    
    # Series asignadas a este establecimiento
    series_asignadas = Column(JSON)  # {"facturas": ["F001"], "boletas": ["B001"]}
    
    # Es establecimiento principal?
    es_principal = Column(Boolean, default=False)
    
    # Estado
    activo = Column(Boolean, default=True)
    
    # Metadata
    creado_en = Column(DateTime, default=utc_now)
    actualizado_en = Column(DateTime, default=utc_now, onupdate=utc_now)
    
    # Relaciones
    emisor = relationship("Emisor", back_populates="establecimientos")
    
    # Índices
    __table_args__ = (
        Index('idx_establecimiento_emisor_codigo', 'emisor_id', 'codigo', unique=True),
    )


# ========================================
# COMPROBANTE TEMPLATE (Favoritos)
# ========================================

class ComprobanteTemplate(Base):
    __tablename__ = 'comprobante_template'
    
    id = Column(String, primary_key=True, default=gen_uuid)
    emisor_id = Column(String, ForeignKey('emisor.id'), nullable=False)
    
    # Identificación
    nombre = Column(String(200), nullable=False)  # "Venta Gloria típica"
    descripcion = Column(String(500))
    
    # Tipo de comprobante
    tipo_documento = Column(String(2))  # '01', '03'
    
    # Cliente predefinido (opcional)
    cliente_id = Column(String, ForeignKey('cliente.id'))
    
    # Items predefinidos (JSON)
    items_json = Column(JSON)

    '''
    [
        {
            "producto_id": "uuid",
            "cantidad": 10,
            "precio_unitario": 25.50
        }
    ]
    '''
    
    # Uso
    es_favorito = Column(Boolean, default=True)
    veces_usado = Column(Integer, default=0)
    ultimo_uso = Column(DateTime)
    
    # Metadata
    creado_en = Column(DateTime, default=utc_now)
    actualizado_en = Column(DateTime, default=utc_now, onupdate=utc_now)
    
    # Relaciones
    emisor = relationship("Emisor")
    cliente = relationship("Cliente")
    
    # Índices
    __table_args__ = (
        Index('idx_template_emisor_favorito', 'emisor_id', 'es_favorito'),
    )

# ========================================
# ACTUALIZAR Comprobante con relación Cliente
# ========================================

# Agregar columna a Comprobante (si no existe)
# Comprobante.cliente_id = Column(String, ForeignKey('cliente.id'))
# Comprobante.cliente = relationship("Cliente", back_populates="comprobantes")


class Categoria(Base):
    __tablename__ = "categoria"
    
    id = Column(String(36), primary_key=True, default=lambda: str(uuid4()))
    emisor_id = Column(String(36), ForeignKey("emisor.id"), nullable=False)
    nombre = Column(String(100), nullable=False)
    descripcion = Column(Text)
    activo = Column(Boolean, default=True)
    creado_en = Column(DateTime, default=datetime.utcnow)
    
    # Relaciones
    emisor = relationship("Emisor", back_populates="categorias")



class ApiLog(Base):
    """Log de llamadas a la API pública"""
    __tablename__ = "api_log"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid4()))
    emisor_id = Column(String(36), ForeignKey("emisor.id"))
    endpoint = Column(String(100))
    metodo = Column(String(10))
    request_body = Column(Text)
    response_code = Column(Integer)
    response_body = Column(Text)
    ip_origen = Column(String(50))
    duracion_ms = Column(Integer)
    creado_en = Column(DateTime, default=datetime.utcnow)

    # Relación
    emisor = relationship("Emisor")


# ========================================
# RESUMEN DIARIO DE BOLETAS (RC)
# ========================================

class ResumenDiario(Base):
    """Resumen Diario de Boletas enviado a SUNAT (sendSummary / getStatus)."""
    __tablename__ = "resumen_diario"

    id = Column(String(36), primary_key=True, default=gen_uuid)
    emisor_id = Column(String(36), ForeignKey("emisor.id"), nullable=False)

    fecha_referencia = Column(Date, nullable=False)
    correlativo = Column(Integer, nullable=False)

    zip_name = Column(String(100))
    ticket = Column(String(50))
    estado = Column(String(20), default='enviado')

    cdr_xml = Column(LargeBinary)
    codigo_sunat = Column(String(10))
    descripcion_sunat = Column(Text)

    boletas_incluidas = Column(Integer)

    created_at = Column(DateTime, default=utc_now)
    updated_at = Column(DateTime, default=utc_now, onupdate=utc_now)

    emisor = relationship("Emisor")

    __table_args__ = (
        Index('idx_resumen_emisor_fecha', 'emisor_id', 'fecha_referencia', 'correlativo', unique=True),
    )


# ========================================
# GUÍA DE REMISIÓN ELECTRÓNICA REMITENTE (GRE, tipo 09)
# ========================================

class GuiaRemision(Base):
    """Guía de Remisión Electrónica Remitente (DespatchAdvice UBL 2.1, tipo 09).
    Alineada a la convención de Comprobante (XML firmado en columna binaria)."""
    __tablename__ = 'guias_remision'

    id = Column(String(36), primary_key=True, default=gen_uuid)
    emisor_id = Column(String(36), ForeignKey('emisor.id'), nullable=False)

    serie = Column(String(4), nullable=False)            # ej. T060
    numero = Column(Integer, nullable=True)              # NULL en borrador; se asigna al confirmar envío

    fecha_emision = Column(Date, nullable=False)
    fecha_inicio_traslado = Column(Date, nullable=False)

    # Traslado
    motivo_traslado = Column(String(2), nullable=False)   # catálogo 20
    descripcion_motivo = Column(String(255))              # obligatorio si motivo=13
    modalidad_traslado = Column(String(2), nullable=False)  # catálogo 18: 01=Público, 02=Privado
    peso_bruto_total = Column(Numeric(12, 3), nullable=False)
    unidad_peso = Column(String(5), default='KGM')
    numero_bultos = Column(Integer, nullable=True)
    indicador_vehiculo_m1l = Column(Boolean, default=False)

    # Destinatario
    dest_tipo_doc = Column(String(1))
    dest_num_doc = Column(String(15))
    dest_razon_social = Column(String(500))

    # Punto de partida
    partida_ubigeo = Column(String(6))
    partida_direccion = Column(String(500))

    # Punto de llegada
    llegada_ubigeo = Column(String(6))
    llegada_direccion = Column(String(500))

    # Transporte privado (modalidad 02; no requeridos si indicador_vehiculo_m1l=True)
    vehiculo_placa = Column(String(20), nullable=True)
    conductor_tipo_doc = Column(String(1), nullable=True)
    conductor_num_doc = Column(String(15), nullable=True)
    conductor_nombres = Column(String(200), nullable=True)
    conductor_licencia = Column(String(20), nullable=True)

    # Transporte público (modalidad 01)
    transportista_tipo_doc = Column(String(1), nullable=True)
    transportista_num_doc = Column(String(15), nullable=True)
    transportista_razon_social = Column(String(500), nullable=True)

    # Factura vinculada (opcional)
    comprobante_id = Column(String(36), ForeignKey('comprobante.id'), nullable=True)

    # Estado SUNAT
    estado = Column(String(32), default='pendiente')
    # pendiente/enviado/aceptado/aceptado_observado/rechazado/error
    num_ticket = Column(String(50))
    cdr_codigo = Column(String(10))
    cdr_descripcion = Column(Text)
    hash_cpe = Column(String(100))                        # DigestValue

    # XML firmado y CDR (mismo patrón binario que Comprobante.xml)
    xml_firmado = Column(LargeBinary)
    cdr_zip = Column(LargeBinary)                         # zip CDR devuelto por SUNAT
    pdf = Column(LargeBinary)                             # representación impresa A4 con QR (cache, patrón Comprobante.pdf)

    created_at = Column(DateTime, default=utc_now)
    updated_at = Column(DateTime, default=utc_now, onupdate=utc_now)

    emisor = relationship("Emisor")
    comprobante = relationship("Comprobante")
    items = relationship('GuiaRemisionItem', back_populates='guia',
                         cascade='all, delete-orphan', order_by='GuiaRemisionItem.orden')
    docs_relacionados = relationship('GuiaRemisionDocRelacionado', back_populates='guia',
                                     cascade='all, delete-orphan', order_by='GuiaRemisionDocRelacionado.orden')

    __table_args__ = (
        Index('idx_guia_emisor_serie_numero', 'emisor_id', 'serie', 'numero', unique=True),
    )


class GuiaRemisionDocRelacionado(Base):
    """Documentos relacionados de una GRE (trazabilidad). Catálogo SUNAT de
    documentos relacionados: 01=Factura, 09=Guía remitente, 50=DAM,
    04=Liquidación de compra, 99=Otros (con descripción)."""
    __tablename__ = 'guias_remision_docs_relacionados'

    id = Column(String(36), primary_key=True, default=gen_uuid)
    guia_id = Column(String(36), ForeignKey('guias_remision.id'), nullable=False)
    orden = Column(Integer, nullable=False, default=1)
    tipo_doc = Column(String(2), nullable=False)          # catálogo doc. relacionados
    descripcion = Column(String(255), nullable=True)      # obligatorio si tipo_doc=99
    numero = Column(String(50), nullable=False)
    emisor_doc_ruc = Column(String(11), nullable=True)    # RUC del emisor del doc (opcional)

    guia = relationship('GuiaRemision', back_populates='docs_relacionados')


class GuiaRemisionItem(Base):
    __tablename__ = 'guias_remision_items'

    id = Column(String(36), primary_key=True, default=gen_uuid)
    guia_id = Column(String(36), ForeignKey('guias_remision.id'), nullable=False)
    orden = Column(Integer, nullable=False)
    codigo = Column(String(50), nullable=True)
    descripcion = Column(Text, nullable=False)
    cantidad = Column(Numeric(12, 3), nullable=False)
    unidad_medida = Column(String(3), default='NIU')      # catálogo 03

    guia = relationship('GuiaRemision', back_populates='items')


# ========================================
# STOCK / INVENTARIO (multi-tenant por emisor)
# ========================================

# Hora de Perú (America/Lima = UTC-5, sin DST), naive
PERU_TZ = timezone(timedelta(hours=-5))


def peru_now():
    """Datetime actual en hora de Perú (naive)."""
    return datetime.now(tz=PERU_TZ).replace(tzinfo=None)


class MovimientoStock(Base):
    """Kardex: un movimiento por entrada/salida/ajuste de un producto.
    Opera sobre la tabla 'producto' (catálogo existente); el control de stock
    vive en producto.stock_actual / producto.maneja_stock."""
    __tablename__ = 'movimientos_stock'

    id = Column(String(36), primary_key=True, default=gen_uuid)
    emisor_id = Column(String(36), ForeignKey('emisor.id'), nullable=False)
    producto_id = Column(String(36), ForeignKey('producto.id'), nullable=False)

    tipo = Column(String(10), nullable=False)            # entrada/salida/ajuste
    cantidad = Column(Numeric(12, 3), nullable=False)
    saldo_resultante = Column(Numeric(12, 3), nullable=False)

    origen_tipo = Column(String(12))                     # comprobante/guia/manual
    origen_id = Column(String(36), nullable=True)
    glosa = Column(String(255))

    fecha = Column(DateTime, default=peru_now)           # hora Perú
    created_at = Column(DateTime, default=utc_now)

    producto = relationship('Producto')

    __table_args__ = (
        Index('idx_mov_stock_emisor_fecha', 'emisor_id', 'fecha'),
        Index('idx_mov_stock_producto', 'producto_id'),
        Index('idx_mov_stock_origen', 'origen_tipo', 'origen_id'),
    )