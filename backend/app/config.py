from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = 'ai-test-workbench'
    environment: str = 'development'
    debug: bool = True
    database_url: str = 'sqlite+aiosqlite:///./app.db'
    redis_url: str = 'redis://localhost:6379/0'
    llm_provider: str = 'mock'
    llm_base_url: str = 'http://localhost:11434/v1'
    llm_api_key: str = 'mock-key'
    llm_model: str = 'mock-model'

    model_config = SettingsConfigDict(env_file='.env', extra='ignore')


@lru_cache
def get_settings() -> Settings:
    return Settings()
