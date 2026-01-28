import os
from pydantic import Field, AliasChoices
from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    # App Settings
    APP_NAME: str = "AgentShield Core"
    BASE_URL: str = Field(default="https://api.agentshield.com")
    DEBUG: bool = False
    PORT: int = 8000
    
    # Security
    ENVIRONMENT: str = Field(default="production")
    SECRET_KEY: str = Field(default="dev-secret-key-change-me", validation_alias=AliasChoices("JWT_SECRET_KEY", "ASARL_SECRET_KEY", "SECRET_KEY"))
    ALGORITHM: str = "HS256"
    CLOUDFLARE_PROXY_SECRET: str = Field(default="")
    
    # Whitelist
    AUTH_WHITELIST: list[str] = [
        "/health",
        "/docs",
        "/openapi.json",
        "/v1/webhook",
        "/v1/public/tenant-config",
        "/v1/signup",
        "/v1/onboarding/organizations",
        "/v1/onboarding/invite",
    ]
    
    # Defaults
    DEFAULT_ROLE: str = "member"
    DEFAULT_FUNCTION: str = "Employee"
    DEFAULT_DEPT: str = "General"
    DEFAULT_REGION: str = "eu"
    
    # Supabase
    SUPABASE_URL: str = Field(default="")
    SUPABASE_SERVICE_KEY: str = Field(default="")
    
    # Redis
    REDIS_URL: str = Field(default="redis://localhost:6379")
    
    # AI Providers
    OPENAI_API_KEY: str = Field(default="")
    ANTHROPIC_API_KEY: str = Field(default="")
    
    # Resend (Email)
    RESEND_API_KEY: str = Field(default="")
    
    # Monitoring
    LOGTAIL_SOURCE_TOKEN: str = Field(default="")
    
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

settings = Settings()
