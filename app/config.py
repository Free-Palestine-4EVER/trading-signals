from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    telegram_bot_token: str
    telegram_chat_id: str
    webhook_secret: str

    polygon_api_key: str | None = None
    newsapi_key: str | None = None
    anthropic_api_key: str | None = None
    gemini_api_key: str | None = None
    groq_api_key: str | None = None

    reddit_client_id: str | None = None
    reddit_client_secret: str | None = None
    reddit_user_agent: str = "trading-signals/0.1"

    weight_technical: float = 0.30
    weight_options: float = 0.30
    weight_news: float = 0.20
    weight_sentiment: float = 0.20

    db_path: str = "signals.db"


settings = Settings()
