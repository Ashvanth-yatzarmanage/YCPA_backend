import secrets
from pathlib import Path
from typing import Any

from pydantic import (
    Field,
    PostgresDsn,
    SecretStr,
    computed_field,
    field_validator,
)
from pydantic_settings import BaseSettings, SettingsConfigDict

BASE_DIR = Path(__file__).resolve().parents[3]


class BaseAppSettings(BaseSettings):

    ENVIRONMENT: str = "production"

    model_config = SettingsConfigDict(
        env_file=BASE_DIR / ".env",
        env_file_encoding="utf-8",
        env_ignore_empty=True,
        extra="ignore",
        case_sensitive=True,
    )
    APP_NAME: str = "MyApp API"
    APP_URL: str = "http://localhost:8000"
    DEBUG: bool = False
    API_V1_PREFIX: str = "/api/v1"

    COGNITO_USER_POOL_ID: str = Field(..., description="Cognito User Pool ID")
    COGNITO_APP_CLIENT_ID: str = Field(..., description="Cognito App Client ID")
    GEMINI_API_KEY: SecretStr = Field(..., description="Google Gemini API Key")

    LOG_LEVEL: str = "INFO"  # DEBUG, INFO, WARNING, ERROR
    LOG_DIR: str = "./logs"

    SECRET_KEY: SecretStr = Field(
        default_factory=lambda: SecretStr(secrets.token_urlsafe(32))
    )
    JWT_SECRET: SecretStr = Field(
        default_factory=lambda: SecretStr(secrets.token_urlsafe(32))
    )
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60 * 24

    CORS_ORIGINS: list[str] = ["http://localhost:3000", "http://localhost:5173","https://app.nithinkcn.com","http://localhost:4173"]
    CORS_ALLOW_CREDENTIALS: bool = True
    CORS_ALLOW_METHODS: list[str] = ["*"]
    CORS_ALLOW_HEADERS: list[str] = ["*"]



    POSTGRES_HOST: str = "localhost"
    POSTGRES_PORT: int = 5432
    POSTGRES_USER: str = "postgres"
    POSTGRES_PASSWORD: SecretStr = Field(default_factory=lambda: SecretStr("12345"))
    POSTGRES_DB: str = "ifc"


    DB_POOL_SIZE: int = 5
    DB_MAX_OVERFLOW: int = 10
    DB_ECHO: bool = False
    DB_USE_SSL: bool = False
    DB_POOL_PRE_PING: bool = True
    DB_POOL_RECYCLE: int = 3600

    SUPERADMIN_EMAIL: str | None = None
    SUPERADMIN_PASSWORD: SecretStr | None = None
    SUPERADMIN_FULL_NAME: str | None = None

    REDIS_URL: str | None = None

    DATABASE_URL: PostgresDsn = Field(..., description="Async Database URL")
    DATABASE_URL_SYNC: PostgresDsn = Field(..., description="Sync Database URL")

    # AWS Configuration
    AWS_REGION: str = Field(..., description="AWS region for Cognito and S3")
    AWS_ACCESS_KEY_ID: str = Field(..., description="AWS Access Key ID")
    AWS_SECRET_ACCESS_KEY: SecretStr = Field(..., description="AWS Secret Access Key")

    S3_BUCKET_NAME: str = Field(default="ifc-uploads-prod", description="S3 bucket name for file uploads")
    S3_MAX_FILE_SIZE: int = Field(default=100 * 1024 * 1024, description="Maximum file size in bytes (default 100MB)")

    SAMPLE_IFC_KEY: str = Field(
        default="uploads/a7fcee56-71bf-45cb-99c2-a5f529e041ff.ifc",
        description="S3 key for sample IFC file"
    )
    SAMPLE_FRAG_KEY: str = Field(
        default="uploads/a7fcee56-71bf-45cb-99c2-a5f529e041ff.frag",
        description="S3 key for sample frag file"
    )
    SAMPLE_FILE_NAME: str = Field(
        default="Sample BIM Model",
        description="Display name for sample file"
    )

    NEO4J_URI: str = Field(
        default="",
        description="Neo4j Aura URI e.g. neo4j+s://xxxxxxxx.databases.neo4j.io"
    )
    NEO4J_USER: str = Field(default="neo4j")
    NEO4J_PASSWORD: SecretStr = Field(
        default=SecretStr(""),
        description="Neo4j Aura password"
    )

    QDRANT_URL: str = Field(
        default=":memory:",
        description="Qdrant URL: ':memory:' | 'http://localhost:6333' | Qdrant Cloud URL"
    )
    QDRANT_API_KEY: SecretStr = Field(
        default=SecretStr(""),
        description="Qdrant Cloud API key (leave empty for local)"
    )

    SMTP_HOST: str = ""
    SMTP_PORT: int = 587
    SMTP_USER: str = ""
    SMTP_PASSWORD: str = ""
    SMTP_FROM: str = "noreply@ycpa.com"
    FRONTEND_URL: str = "https://app.nithinkcn.com"

    RAZORPAY_KEY_ID: str = Field(..., description="Razorpay Key ID")
    RAZORPAY_KEY_SECRET: SecretStr = Field(..., description="Razorpay Key Secret")

    @computed_field
    @property
    def COGNITO_JWKS_URL(self) -> str:
        return (
            f"https://cognito-idp.{self.AWS_REGION}.amazonaws.com/"
            f"{self.COGNITO_USER_POOL_ID}/.well-known/jwks.json"
        )

    @computed_field
    @property
    def COGNITO_ISSUER(self) -> str:
        return (
            f"https://cognito-idp.{self.AWS_REGION}.amazonaws.com/"
            f"{self.COGNITO_USER_POOL_ID}"
        )

    @field_validator("CORS_ORIGINS", mode="before")
    @classmethod
    def parse_cors_origins(cls, v: Any) -> list[str]:
        if isinstance(v, str):
            return [origin.strip() for origin in v.split(",")]
        return v
