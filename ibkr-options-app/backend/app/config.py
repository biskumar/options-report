from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    ib_host: str = "127.0.0.1"
    ib_port: int = 7496  # 7496 live TWS, 7497 paper TWS, 4001 live Gateway, 4002 paper Gateway
    ib_client_id: int = 101  # kept distinct from options_report.py's 12/13/14
    ib_account: str = ""  # optional: restrict to a specific account id if multiple are linked

    allow_orders: bool = False  # dry-run by default; flip to true in .env when ready to test live

    cors_origins: list[str] = ["http://localhost:5175"]

    telegram_token: str = ""  # optional: leave blank to disable alert push notifications
    telegram_chat_id: str = ""

    model_config = SettingsConfigDict(env_file=".env")


settings = Settings()
