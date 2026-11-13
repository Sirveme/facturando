from pydantic_settings import BaseSettings
from pydantic import Field

class Settings(BaseSettings):
    database_url: str = Field(..., env='DATABASE_URL')
    redis_url: str | None = Field(None, env='REDIS_URL')
    sunat_environment: str = Field('beta', env='SUNAT_ENVIRONMENT')
    sunat_timeout: int = Field(30, env='SUNAT_TIMEOUT')
    secret_key: str = Field(..., env='SECRET_KEY')
    encryption_key: str = Field(..., env='ENCRYPTION_KEY')
    jwt_secret: str = Field(..., env='JWT_SECRET')
    test_mode: bool = Field(False, env='TEST_MODE')
    debug: bool = Field(True, env='DEBUG')
    log_level: str = Field('INFO', env='LOG_LEVEL')
    environment: str = Field('development', env='ENVIRONMENT')
    # Busca la clase Settings y AGREGA este campo:
    APIS_NET_PE_TOKEN: str = Field("", env="APIS_NET_PE_TOKEN")
    # Cache-busting de estáticos propios: bumpea este valor (o la env APP_VERSION)
    # en cada deploy para invalidar CSS/JS cacheados por el navegador.
    # También es el sello de versión visible en /health para confirmar qué corre en prod.
    APP_VERSION: str = Field("2026.11.13.1", env="APP_VERSION")
    # Sello de build OPCIONAL (manual, via env). Si queda vacío, /health calcula un
    # fingerprint automático del código Python desplegado (hash de src/**/*.py), que
    # cambia solo cuando cambia el código → detecta "deploy no tomó los cambios".
    BUILD_TAG: str = Field("", env="BUILD_TAG")

    # ── Vigilante de salud (monitoreo) + Telegram. Secretos SOLO por env, nunca en código.
    #    El código debe compilar/arrancar aunque estén vacías (solo se usan para alertar/ver).
    TELEGRAM_BOT_TOKEN: str = Field("", env="TELEGRAM_BOT_TOKEN")
    TELEGRAM_CHAT_ID: str = Field("", env="TELEGRAM_CHAT_ID")
    WATCHDOG_VIEW_TOKEN: str = Field("", env="WATCHDOG_VIEW_TOKEN")
    # Umbrales (minutos / hora), configurables por env.
    WD_COLA_MIN: int = Field(15, env="WD_COLA_MIN")            # antigüedad para "cola atascada"
    WD_COLA_MAX_H: int = Field(24, env="WD_COLA_MAX_H")        # ventana máx (ignora rezagos ancianos)
    WD_HEARTBEAT_MIN: int = Field(20, env="WD_HEARTBEAT_MIN")  # debe ser > cadencia del cron (15m)
    WD_NOEMISION_HORA_LIMA: int = Field(20, env="WD_NOEMISION_HORA_LIMA")
    WD_COOLDOWN_MIN: int = Field(60, env="WD_COOLDOWN_MIN")    # anti-spam: no repetir antes de esto
    WD_ESTADOS_COLA: str = Field("pendiente,encolado,enviando,reintentando", env="WD_ESTADOS_COLA")

    # Clasificación CDR (Opción C): códigos de observación 4xxx "informativos" (ruido
    # sistémico) que NO cambian el estado → el comprobante queda 'aceptado' aunque SUNAT
    # devuelva estas notas (el detalle igual se guarda en RespuestaSunat.observaciones).
    # Cualquier otro 4xxx → 'aceptado_con_observaciones'. 4252=@listName (ya corregido en
    # xml_generator; histórico); 4094=domicilio fiscal del emisor en "-".
    CODIGOS_OBS_INFORMATIVOS: str = Field("4094,4252", env="CODIGOS_OBS_INFORMATIVOS")

    # ── Validación de receptor contra padrón (Task A). APAGADO por defecto.
    #    Cuando el receptor es RUC: consulta el padrón y compara la razón social.
    #    - No coincide (padrón respondió) → rechazo con mensaje claro.
    #    - Padrón sin respuesta → fail-open: emite + marca receptor_no_validado + alerta
    #      Telegram. Salvo "modo estricto" (por RUC de emisor) → rechaza.
    VALIDAR_RECEPTOR: bool = Field(False, env="VALIDAR_RECEPTOR")
    VALIDAR_RECEPTOR_UMBRAL: int = Field(90, env="VALIDAR_RECEPTOR_UMBRAL")   # % similitud mínima
    VALIDAR_RECEPTOR_ESTRICTO: str = Field("", env="VALIDAR_RECEPTOR_ESTRICTO")  # RUCs emisor (coma) en modo estricto

    class Config:
        env_file = ".env"

settings = Settings()
