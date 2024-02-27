from __future__ import annotations

import httpx
import urllib.request
import logging
from typing import Literal, Any
from pydantic import BaseModel, Field, ConfigDict
from pathlib import Path
from asynctinydb import TinyDB, CachingMiddleware, JSONStorage
from vermils.gadgets.monologger import MonoLogger
from .classes import Task


__all__ = [
    "Config"
]


class BaseConfig(BaseModel):
    model_config = ConfigDict(
        validate_assignment=True,
        populate_by_name=True,
        extra="ignore"
    )


class Config(BaseConfig):
    """
    # Config Class
    """
    class ClientConfig(BaseConfig):
        """
        # ClientConfig Class
        """
        user_agent: str = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36"
        timeout: float = 10.0
        proxy: str | None = None
        max_retries: int = 5
        trust_env: bool = True

        def get_cli(self) -> httpx.AsyncClient:
            """
            # Get Client
            """
            proxy = self.proxy
            if self.proxy is None and self.trust_env:
                sys_proxy = urllib.request.getproxies()
                proxy = sys_proxy.get('https', sys_proxy.get('http'))
            trans = httpx.AsyncHTTPTransport(
                http2=True,
                trust_env=False,
                proxy=proxy,
                retries=self.max_retries,
            )
            return httpx.AsyncClient(
                headers={"User-Agent": self.user_agent},
                transport=trans,
                timeout=self.timeout)

    class DBConfig(BaseConfig):
        """
        # DBConfig Class
        """
        path: Path = Path('db.json')
        write_buffer_size: int = 0

        def get_db(self, dir_path: Path | None = None) -> TinyDB:
            """
            # Get DB
            """
            if self.write_buffer_size:
                storage: Any = CachingMiddleware(
                    JSONStorage, self.write_buffer_size
                )
            else:
                storage = JSONStorage
            path = dir_path / self.path if dir_path else self.path
            return TinyDB(
                str(path),
                storage=storage,
                indent=2,
                ensure_ascii=False,
            )

    class LoggingConfig(BaseConfig):
        """
        # LoggingConfig Class
        """
        level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = "INFO"
        fmt: str = '%(asctime)s - %(levelname)s - %(message)s'
        dirpath: Path = Path('logs')
        show_console: bool = True

        def get_logger(self, name: str = "root"):
            """
            # Get Logger
            """
            logger = MonoLogger(
                name=name,
                level=self.level,
                path=str(self.dirpath),
                formatter=self.fmt,
            )
            if self.show_console:
                handler = logging.StreamHandler()
                handler.setFormatter(logging.Formatter(self.fmt))
                logger.addHandler(handler)
            return logger

    version: str = "1.0.0"
    tasks: list[Task] = Field(default_factory=list)
    roles: list[Any] = Field(default_factory=list)
    client: ClientConfig = Field(default_factory=ClientConfig)
    db: DBConfig = Field(default_factory=DBConfig)
    logging: LoggingConfig = Field(default_factory=LoggingConfig)
