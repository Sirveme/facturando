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
    APP_VERSION: str = Field("2026.06.15", env="APP_VERSION")

    class Config:
        env_file = ".env"

settings = Settings()
