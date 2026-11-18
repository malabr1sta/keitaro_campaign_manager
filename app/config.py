from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")
    keitaro_base_url: str = ""
    api_key: str = ""
    keitaro_domain_id: str = ""
    keitaro_group_id: str = ""
    keitaro_traffic_source_id: str = ""
    database_url: str = "sqlite:///./data/app.db"
