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

    class Config:
        env_file = ".env"

settings = Settings()
