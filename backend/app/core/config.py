"""统一读取 backend/.env 中的配置。

所有密钥只从环境变量 / .env 读取，代码中不出现真实 Token。
"""

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

# config.py 位于 backend/app/core/，向上三级即 backend/
BACKEND_DIR = Path(__file__).resolve().parents[2]
DATA_DIR = BACKEND_DIR / "data"


class Settings(BaseSettings):
    """项目配置项，字段名自动对应 .env 中的大写变量。"""

    model_config = SettingsConfigDict(
        env_file=BACKEND_DIR / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = "CULTScope"
    app_env: str = "development"
    api_host: str = "127.0.0.1"
    api_port: int = 8000

    tmdb_bearer_token: str = ""
    tmdb_api_base: str = "https://api.themoviedb.org/3"
    tmdb_language: str = "zh-CN"

    mysql_host: str = "127.0.0.1"
    mysql_port: int = 3306
    mysql_user: str = "root"
    mysql_password: str = ""
    mysql_database: str = "cultscope"

    # 前端开发服务器地址，用于 CORS
    cors_origins: list[str] = [
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    ]


settings = Settings()
