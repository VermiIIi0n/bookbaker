from __future__ import annotations

import httpx
import asyncio
from typing import Any
from pydantic import BaseModel, field_validator, ConfigDict
from pydantic import Field, PrivateAttr
from asynctinydb import TinyDB
from datetime import datetime, UTC
from itertools import chain
from vermils.gadgets import LoggerLike


__all__ = [
    "TimeMeta",
    "ImageRef",
    "Line",
    "Episode",
    "Chapter",
    "Book",
    "Context",
    "Task"
]


class TimeMeta(BaseModel):
    """
    # TimeMeta Class
    """
    model_config = ConfigDict(validate_assignment=True)
    created_at: datetime | None = None
    updated_at: datetime | None = None
    saved_at: datetime = Field(default_factory=datetime.utcnow)

    @field_validator("created_at", "updated_at", "saved_at", mode="after")
    def convert_utc(cls, v: datetime | None):
        if v is not None:
            return v.astimezone(UTC)
        return v


class ImageRef(BaseModel):
    """
    # ImageRef Class
    """
    url: str
    alt: str = ''
    time_meta: TimeMeta = Field(default_factory=TimeMeta)


class Line(BaseModel):
    """
    # Line Class
    """
    content: str
    translated: str | None = None
    candidates: dict[str, str] = Field(default_factory=dict)

    def __eq__(self, other: Any) -> bool:
        if isinstance(other, Line):
            return self.content == other.content
        return NotImplemented

    def __str__(self) -> str:
        return self.content

    def __repr__(self) -> str:
        return f"Line(content={self.content!r}, translated={self.translated!r})"


class Episode(BaseModel):
    """
    # Episode Class
    """
    title: str
    title_translated: str | None = None
    notes: str = ''
    notes_translated: str | None = None
    lines: list[Line]
    time_meta: TimeMeta = Field(default_factory=TimeMeta)

    def __eq__(self, other: Any) -> bool:
        if isinstance(other, Episode):
            return self.title == other.title
        return NotImplemented

    @property
    def fully_translated(self) -> bool:
        """
        # Fully Translated
        Check if all lines are translated
        """
        for line in self.lines:
            if not line.content.strip():
                continue
            if line.translated is None:
                return False
        return True

    @property
    def html(self) -> str:
        """
        # HTML
        """
        return '\n'.join(chain(
            (f"<h3>{self.title_translated or self.title}</h3>",
             f"<p>{self.notes_translated or self.notes}</p>",
             "<hr>"),
            (f"<p>{line.translated or ''}</p>" for line in self.lines)
        ))

    @property
    def raw_html(self) -> str:
        """HTML of the original content"""
        return '\n'.join(chain(
            (f"<h3>{self.title}</h3>",
             f"<p>{self.notes}</p>",
             "<hr>"),
            (f"<p>{line.content}</p>" for line in self.lines)
        ))


class Chapter(BaseModel):
    """
    # Chapter Class
    """
    title: str
    title_translated: str | None = None
    cover: ImageRef | None = None
    episodes: list[Episode] = Field(default_factory=list)
    time_meta: TimeMeta = Field(default_factory=TimeMeta)

    def get_episode(self, title: str) -> Episode | None:
        """
        # Get Episode
        """
        for episode in self.episodes:
            if episode.title == title:
                return episode
        return None

    @property
    def fully_translated(self) -> bool:
        return all(episode.fully_translated for episode in self.episodes)

    @property
    def html(self) -> str:
        return '\n'.join(chain(
            (f"<h2>{self.title_translated or self.title}</h2>",),
            (episode.html for episode in self.episodes)
        )
        )

    def __eq__(self, other: Any) -> bool:
        if isinstance(other, Chapter):
            return self.title == other.title
        return NotImplemented


class Book(BaseModel):
    """
    # Book Class
    """
    title: str
    title_translated: str | None = None
    author: str
    url: str | None = None
    series: str | None = None
    series_translated: str | None = None
    tags: set[str] = Field(default_factory=set)
    cover: ImageRef | None = None
    description: str = ''
    description_translated: str | None = None
    time_meta: TimeMeta = Field(default_factory=TimeMeta)
    chapters: list[Chapter] = Field(default_factory=list)

    def get_chapter(self, title: str) -> Chapter | None:
        """
        # Get Chapter
        """
        for chapter in self.chapters:
            if chapter.title == title:
                return chapter
        return None

    @property
    def fully_translated(self) -> bool:
        return all(chapter.fully_translated for chapter in self.chapters)

    @property
    def html(self) -> str:
        return '\n'.join(chain(
            (f"<h1>{self.title_translated or self.title}</h1>",
             f"<p>{self.description_translated or self.description}</p>",
             "<hr>"),
            (chapter.html for chapter in self.chapters)
        ))

    def __eq__(self, other: Any) -> bool:
        if isinstance(other, Book):
            return (self.title == other.title
                    and self.author == other.author)
        return NotImplemented


class Context:
    def __init__(self,
                 db: TinyDB,
                 client: httpx.AsyncClient,
                 logger: LoggerLike,
                 extra: dict[str, Any] | None = None):
        self.db = db
        self.logger = logger
        self.client = client
        self.extra = extra or {}


class Task(BaseModel):
    """
    # Task Class
    """
    url: str = ''
    friendly_name: str = ''
    sauce_lang: str = "JA"
    target_lang: str = "ZH"
    crawler: str | None = None
    translator: str | list[str] | None = None
    exporter: str | list[str] | None = None
    glossaries: list[tuple[str, str]] = Field(default_factory=list)
    extra: dict[str, Any] = Field(default_factory=dict)
    _lock: asyncio.Lock = PrivateAttr(default_factory=asyncio.Lock)

    @property
    def lock(self) -> asyncio.Lock:
        return self._lock
