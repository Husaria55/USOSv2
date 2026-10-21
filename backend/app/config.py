from pydantic_settings import BaseSettings, SettingsConfigDict


DEV_SECRET = "dev-only-secret-change-me-in-production-0123456789"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="USOS_", env_file=".env", extra="ignore")

    database_url: str = "postgresql+asyncpg://usos:usos@localhost:5433/usos"
    db_pool_size: int = 10
    db_max_overflow: int = 5

    jwt_secret: str = DEV_SECRET
    jwt_ttl_hours: int = 12
    # Koszt bcrypt: 10 to ok. 50 ms CPU na logowanie. Przy otwarciu tury loguje
    # się naraz kilka tysięcy osób, więc wyższy koszt zjadłby procesor API.
    bcrypt_rounds: int = 10

    # Kontrola wejścia (na proces API). Nadmiar dostaje 429/503 z Retry-After
    # zamiast czekać w kolejce do bazy.
    enroll_concurrency: int = 8          # równoczesne transakcje zapisu
    read_concurrency: int = 16           # równoczesne ciężkie odczyty (status grup)
    enroll_queue_timeout_s: float = 2.0  # ile żądanie może czekać na wolny slot
    rate_limit_per_minute: int = 60      # operacje zapisu na studenta
    catalog_cache_ttl_s: float = 3.0

    tx_max_retries: int = 5

    smtp_host: str = "localhost"
    smtp_port: int = 1025
    smtp_from: str = "zapisy@usos.local"
    worker_interval_s: float = 5.0


settings = Settings()
