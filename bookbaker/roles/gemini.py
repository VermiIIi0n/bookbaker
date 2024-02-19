from __future__ import annotations

import ujson as json
import asyncio
from typing import cast, overload
from uuid import uuid4
from pydantic import Field
from asynctinydb import Query
from gemnine import Bot, Message, Role
from ..misc import LANG_NAME_TABLE

from bookbaker.classes import Context, Task
from ..classes import Book, Chapter, Episode
from .base import BaseTranslator


class GeminiTranslator(BaseTranslator):
    """
    # GeminiTranslator Class
    """
    name: str = Field(default_factory=lambda: f"gemini-{str(uuid4())[:8]}")
    description: str = "A translator for gemini.com"
    max_retries: int | None = 10
    batch_size: int = 1024
    skip_translated: bool = True
    backend: Bot = Field(
        default_factory=lambda: Bot(model="models/gemini-pro", api_key=''))

    async def translate(
            self,
            episode: Episode,
            task: Task,
            ctx: Context,
            chapter: Chapter | None = None,
            book: Book | None = None,
    ) -> Episode:
        cli = ctx.client
        self.backend._cli = cli
        db = ctx.db
        sauce_lang = LANG_NAME_TABLE.get(task.sauce_lang.upper(), task.sauce_lang)
        target_lang = LANG_NAME_TABLE.get(task.target_lang.upper(), task.target_lang)
        logger = ctx.logger
        sess = self.backend.new_session()
        sess.message_lock = 2  # Prevents first 2 prompts being deleted

        prompt = f"Translate JSON values from {sauce_lang} to {target_lang}.\n"\
            "Keep the original structure of the content.\n"\
            "If the input is a list, the output order should be the same\n"
        if task.glossaries:
            prompt += "Translation reference:\n"
            prompt += '\n'.join(f"{k} : {v}" for k, v in task.glossaries)
        if book is not None:
            prompt += "\nThe book you are translating:\n"
            book_full_meta = {
                "title": book.title,
                "description": book.description,
                "series": book.series,
                "tags": list(book.tags),
            }
            prompt += f"{json.dumps(book_full_meta, ensure_ascii=False)}\n"
        if chapter is not None:
            prompt += "\nThe chapter you are translating:\n"
            chapter_meta: dict[str, str | None] = {
                "title": chapter.title,
            }
            prompt += f"{json.dumps(chapter_meta, ensure_ascii=False)}\n"

        prompt += "\nThe episode you are translating:\n"
        episode_meta: dict[str, str | None] = {
            "title": episode.title,
            "notes": episode.notes,
        }
        prompt += f"{json.dumps(episode_meta, ensure_ascii=False)}\n"
        prompt += "\nYou can start translating now: {\"series\": null, \"test_text\": \"Apple is yummy!\","\
            "\"test_array\": [\"Hello, world!\", \"How are you?\"]}"

        logger.debug("%s: generated prompt: %s", self, prompt)

        sess.append(Message(role=Role.User, parts=prompt))
        sess.append(Message(role=Role.Model, parts="{\"series\": null, \"test_text\": \"苹果很好吃！\""
                            ",\"test_array\": [\"你好，世界！\", \"你好吗？\"]}"))

        @overload
        async def translate(c: dict[str, str | None]) -> dict[str, str | None]:
            ...

        @overload
        async def translate(c: list[str]) -> list[str]:
            ...

        async def translate(c: list[str] | dict[str, str | None]) -> list[str] | dict[str, str | None]:
            jstr = json.dumps(c, ensure_ascii=False)
            logger.debug("%s: Sending prompt: %s", self, jstr)
            sess_bak = sess.messages.copy()

            retry = 0

            while True:
                resp: str | None = None
                try:
                    resp = await sess.send(jstr)
                    logger.debug("%s: Received response: %s", self, resp)
                    obj = json.loads(cast(str, resp))
                    if isinstance(c, list):
                        if not isinstance(obj, list):
                            raise TypeError("Expected list, got dict")
                        if len(obj) != len(c):
                            raise ValueError("Length mismatch")
                    else:
                        if not isinstance(obj, dict):
                            raise TypeError("Expected dict, got list")
                        if obj.keys() != c.keys():
                            raise ValueError("Key mismatch")

                    return obj

                except Exception as e:
                    logger.debug("%s: Failed to get valid response: %s", self, resp)
                    logger.exception(e)
                    sess.messages = sess_bak
                    retry += 1
                    if self.max_retries is not None and retry > self.max_retries:
                        raise RuntimeError(
                            "Failed to get valid response in %d retries" % self.max_retries)
                    await asyncio.sleep(1)
                    continue

        if book is not None and None in (
            book.title_translated,
            book.description_translated,
            book.series_translated if book.series else ''
        ):
            book_meta: dict[str, str | None] = {
                "title": book.title,
                "description": book.description,
                "series": book.series
            }
            book_meta = await translate(book_meta)
            book.title_translated = book_meta["title"]
            book.description_translated = book_meta["description"]
            book.series_translated = book_meta["series"]

        if chapter is not None and chapter.title_translated is None:
            chapter_meta = {
                "title": chapter.title
            }
            chapter_meta = await translate(chapter_meta)
            chapter.title_translated = chapter_meta["title"]

        episode_meta = await translate(episode_meta)
        episode.title_translated = episode_meta["title"]
        episode.notes_translated = episode_meta["notes"]

        indexes = list[int]()
        contents = list[str]()
        c_cnt = 0
        MAX_CNT = self.batch_size

        for i, line in enumerate(episode.lines):
            if not line.content.strip():
                continue
            if self.skip_translated and line.translated is not None:
                continue
            indexes.append(i)
            contents.append(line.content)
            c_cnt += len(line.content)
            if c_cnt > MAX_CNT:
                translated = await translate(contents)
                for j, v in zip(indexes, translated):
                    o = episode.lines[j].content
                    episode.lines[j].translated = v
                    if not v.strip():
                        logger.warning("%s: Empty translation for %s", self, o)
                indexes.clear()
                contents.clear()
                c_cnt = 0

        if indexes:
            translated = await translate(contents)
            for j, v in zip(indexes, translated):
                episode.lines[j].translated = v

        q = Query()
        if book is not None:
            await db.upsert(book.model_dump(mode="json"),
                            q.title == book.title and q.author == book.author)

        return episode
