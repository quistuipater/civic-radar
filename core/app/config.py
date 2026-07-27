from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Per-city scalar values below all have generic fallback defaults; each
    # city's docker-compose.yml overrides them via environment variables
    # (see cities/<city>/docker-compose.yml). Structured per-city data that
    # doesn't fit a scalar env var (e.g. crime_data.py's AGENCY_CONFIG) lives
    # in app/city_config.py instead -- see that module's docstring.
    project_name: str = "Civic Radar"

    database_url: str = "postgresql+psycopg://civic_radar:civic_radar_dev_password@postgres:5432/civic_radar"
    archive_root: str = "/archive"

    ollama_base_url: str = "http://ollama:11434"
    ollama_triage_model: str = "llama3.1:8b"
    ollama_analysis_model: str = "llama3.1:8b"
    ollama_embedding_model: str = "nomic-embed-text"

    whisperx_base_url: str = "http://madhatter.local:8091"

    worker_tick_seconds: int = 60
    ai_job_concurrency: int = 1
    http_user_agent: str = "CivicRadar/0.1 (+local civic monitoring)"

    api_host: str = "0.0.0.0"
    api_port: int = 8000


settings = Settings()
