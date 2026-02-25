"""
Modelos SQLAlchemy para el Panel del Contador
Archivo: src/models/contador.py
"""
from sqlalchemy import Column, Integer, String, Boolean, DateTime, ForeignKey, Numeric, Text, CheckConstraint
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from src.models.models import Base  # Importar el Base existente


class Contador(Base):
    __tablename__ = "contador"

    id = Column(Integer, primary_key=True, autoincrement=True)
    ruc = Column(String(11), unique=True, nullable=False)
    razon_social = Column(String(200), nullable=False)
    nombre_comercial = Column(String(200))

    # Contacto
    nombre_contacto = Column(String(150))
    email = Column(String(150), unique=True, nullable=False)
    telefono = Column(String(20))
    whatsapp = Column(String(20))
    direccion = Column(String(300))

    # Auth
    password_hash = Column(String(200), nullable=False)

    # Plan
    plan = Column(String(20), default="free")
    max_clientes = Column(Integer, default=5)

    # Gestión del estudio
    cantidad_trabajadores = Column(Integer, default=0)
    costo_planilla_mensual = Column(Numeric(12, 2), default=0)
    gastos_fijos_mensual = Column(Numeric(12, 2), default=0)

    # Metadata
    activo = Column(Boolean, default=True)
    ultimo_login = Column(DateTime(timezone=True))
    creado_en = Column(DateTime(timezone=True), server_default=func.now())
    actualizado_en = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    # Relationships
    clientes = relationship("ContadorCliente", back_populates="contador", cascade="all, delete-orphan")
    trabajadores = relationship("ContadorTrabajador", back_populates="contador", cascade="all, delete-orphan")
    gastos_fijos = relationship("ContadorGastoFijo", back_populates="contador", cascade="all, delete-orphan")


class ContadorCliente(Base):
    __tablename__ = "contador_cliente"

    id = Column(Integer, primary_key=True, autoincrement=True)
    contador_id = Column(Integer, ForeignKey("contador.id", ondelete="CASCADE"), nullable=False)
    emisor_id = Column(String(36), ForeignKey("emisor.id", ondelete="CASCADE"), nullable=False)

    estado = Column(String(20), default="activo")
    ingreso_mensual = Column(Numeric(10, 2), default=0)
    comision_porcentaje = Column(Numeric(5, 2), default=0)
    regimen_tributario = Column(String(50))
    notas = Column(Text)

    fecha_vinculacion = Column(DateTime(timezone=True), server_default=func.now())
    fecha_desvinculacion = Column(DateTime(timezone=True))
    creado_en = Column(DateTime(timezone=True), server_default=func.now())

    # Relationships
    contador = relationship("Contador", back_populates="clientes")
    emisor = relationship("Emisor", backref="contadores_vinculados")


class ContadorTrabajador(Base):
    __tablename__ = "contador_trabajador"

    id = Column(Integer, primary_key=True, autoincrement=True)
    contador_id = Column(Integer, ForeignKey("contador.id", ondelete="CASCADE"), nullable=False)
    nombre = Column(String(150), nullable=False)
    cargo = Column(String(100))
    sueldo_mensual = Column(Numeric(10, 2), default=0)
    essalud = Column(Numeric(10, 2), default=0)
    telefono = Column(String(20))
    activo = Column(Boolean, default=True)
    creado_en = Column(DateTime(timezone=True), server_default=func.now())

    contador = relationship("Contador", back_populates="trabajadores")


class ContadorGastoFijo(Base):
    __tablename__ = "contador_gasto_fijo"

    id = Column(Integer, primary_key=True, autoincrement=True)
    contador_id = Column(Integer, ForeignKey("contador.id", ondelete="CASCADE"), nullable=False)
    concepto = Column(String(200), nullable=False)
    monto_mensual = Column(Numeric(10, 2), nullable=False)
    categoria = Column(String(50), default="operativo")
    activo = Column(Boolean, default=True)
    creado_en = Column(DateTime(timezone=True), server_default=func.now())

    contador = relationship("Contador", back_populates="gastos_fijos")