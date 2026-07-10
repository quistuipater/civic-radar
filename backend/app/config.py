from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql+psycopg://civic_radar:civic_radar_dev_password@postgres:5432/boston_civic_radar"
    archive_root: str = "/archive"

    ollama_base_url: str = "http://ollama:11434"
    ollama_triage_model: str = "llama3.1:8b"
    ollama_analysis_model: str = "llama3.1:8b"
    ollama_embedding_model: str = "nomic-embed-text"

    # No transcription service stood up for Boston yet -- see README's TODO
    # section. Left pointed at madhatter as a placeholder; update once a
    # real meeting-audio source and (if needed) a WhisperX deployment exist
    # for this jurisdiction.
    whisperx_base_url: str = "http://madhatter.local:8091"

    worker_tick_seconds: int = 60
    ai_job_concurrency: int = 1
    http_user_agent: str = "BostonCivicRadar/0.1 (+local civic monitoring)"

    api_host: str = "0.0.0.0"
    api_port: int = 8000


settings = Settings()
