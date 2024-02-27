from __future__ import annotations

import inspect
from importlib import import_module
from abc import abstractmethod, ABC
from typing import AsyncGenerator, Any, TypeVar
from uuid import uuid4
from pydantic import Field, BaseModel, ConfigDict, computed_field
from ..classes import Context, Book, Chapter, Episode, Task


R = TypeVar('R', bound='BaseRole')


__all__ = [
    "BaseRole",
    "BaseCrawler",
    "BaseTranslator",
    "BaseExporter",
    "recover_from_dict",
]


class BaseRole(BaseModel):
    model_config = ConfigDict(extra="allow")
    name: str = Field(default_factory=lambda: f"role-{str(uuid4())[:8]}")
    description: str = ''

    @computed_field
    def classname(self) -> str:
        return self.__class__.__name__

    @computed_field
    def modulename(self) -> str | None:
        mod = inspect.getmodule(self.__class__)
        if mod is None:
            return None
        return mod.__name__

    def __str__(self) -> str:
        return f"{self.classname}({self.name})"

    def __repr__(self) -> str:
        return f"{self.classname}({self.name!r})"


def recover_from_dict(
        d: dict[str, Any],
        type_: type[R] = BaseRole) -> R:  # type: ignore[assignment]
    """
    Recover a BaseRole object from a dictionary
    """
    try:
        mod = import_module(d['modulename'])
        cls = getattr(mod, d['classname'])
        if not issubclass(cls, type_):
            raise ValueError(f"Class {cls} is not a subclass of {type_}")
        return cls(**d)
    except (KeyError, AttributeError, ImportError) as e:
        raise ValueError(f"Failed to recover from dict: {e}") from e


class BaseCrawler(ABC, BaseRole):
    """
    Crawler for syosetu.com
    """
    name: str = Field(default_factory=lambda: f"crawler-{str(uuid4())[:8]}")
    description: str = "Base Crawler"

    @abstractmethod
    def crawl_stream(
            self,
            task: Task,
            ctx: Context,
    ) -> AsyncGenerator[tuple[Task, Book, Chapter, Episode], None]:
        ...


class BaseTranslator(ABC, BaseRole):
    """
    Translator base class
    """
    name: str = Field(default_factory=lambda: f"translator-{str(uuid4())[:8]}")
    description: str = "Base Translator"

    @abstractmethod
    async def translate(
            self,
            episode: Episode,
            task: Task,
            ctx: Context,
            chapter: Chapter | None = None,
            book: Book | None = None,
    ) -> Episode:
        ...


class BaseExporter(ABC, BaseRole):
    """
    Exporter base class
    """
    name: str = Field(default_factory=lambda: f"exporter-{str(uuid4())[:8]}")
    description: str = "Base Exporter"

    @abstractmethod
    async def export(
            self,
            book: Book,
            task: Task,
            ctx: Context,
    ) -> Any:
        ...
