from functools import lru_cache
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    azure_storage_conn_string: str
    storage_container: str
    cdn_base_url: str
    blender_bin: str = "blender"
    log_level: str = "INFO"
    database_url: str = ""
    azure_blob_base_url: str = ""

    model_config = {"env_file": ".env", "extra": "ignore"}


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
