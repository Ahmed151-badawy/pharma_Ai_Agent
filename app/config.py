"""Central configuration, read from environment variables (and a local .env file)."""
from functools import lru_cache

from dotenv import load_dotenv
from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy.engine import URL, make_url

# Export .env values into os.environ so third-party libraries (LangSmith, Groq, ...) see them too.
load_dotenv()


class Settings(BaseSettings):
    model_config = SettingsConfigDict(extra="ignore")

    # --- LLM ---
    groq_api_key: str | None = None
    groq_model: str = "openai/gpt-oss-120b"
    agent_recursion_limit: int = 12
    history_max_messages: int = 30

    # --- Auth ---
    jwt_secret: str | None = Field(
        default=None,
        validation_alias=AliasChoices("jwt_secret", "secret_key", "JWT_SECRET", "SECRET_KEY"),
    )
    jwt_expire_minutes: int = 60
    admin_username: str | None = None
    admin_password: str | None = None

    # --- Database ---
    database_url: str | None = None  # e.g. postgres://user:pass@host/db (Render/Heroku style is accepted)
    db_host: str = "localhost"
    db_port: int = 5432
    db_name: str = "pharma_inventory"
    db_user: str = "postgres"
    db_password: str = "postgres"
    # Optional dedicated read-only role used by the agent's SQL tool (created by scripts/ensure_readonly_role.py)
    readonly_db_user: str = "pharma_ro"
    readonly_db_password: str | None = None

    # --- Knowledge base (RAG) ---
    faiss_index_dir: str = "data/faiss"
    seed_document_path: str = "fda_guidelines.txt"
    embeddings_backend: str = "huggingface"  # "fake" is used by the test-suite
    embedding_model: str = "all-MiniLM-L6-v2"
    retrieval_k: int = 4
    chunk_size: int = 800
    chunk_overlap: int = 100
    max_upload_mb: int = 10
    max_pdf_pages: int = 300

    # --- Inventory ---
    confirmation_ttl_minutes: int = 10

    # --- API protection ---
    rate_limit_enabled: bool = True
    chat_rate_limit_per_minute: int = 20
    login_rate_limit_per_minute: int = 10

    # Comma-separated browser origins allowed to call the API (only needed for a browser-based SPA)
    cors_origins: str = ""

    # --- Logging ---
    log_level: str = "INFO"
    log_json: bool = True

    @property
    def sqlalchemy_url(self) -> URL:
        if self.database_url:
            raw = self.database_url
            for prefix in ("postgres://", "postgresql://"):
                if raw.startswith(prefix):
                    raw = "postgresql+psycopg2://" + raw[len(prefix):]
            return make_url(raw)
        return URL.create(
            "postgresql+psycopg2",
            username=self.db_user,
            password=self.db_password,
            host=self.db_host,
            port=self.db_port,
            database=self.db_name,
        )

    @property
    def readonly_sqlalchemy_url(self) -> URL:
        url = self.sqlalchemy_url
        if self.readonly_db_password:
            url = url.set(username=self.readonly_db_user, password=self.readonly_db_password)
        return url


@lru_cache
def get_settings() -> Settings:
    return Settings()
