from __future__ import annotations

import ujson as json
import asyncio
from typing import overload
from uuid import uuid4
from pydantic import Field
from asynctinydb import Query
from gemnine import Bot, Message, Role, ContentBlockedError
from ..misc import LANG_NAME_TABLE
from ..utils import escape_ruby, unescape_ruby
from ..utils import escape_repetition, unescape_repetition
from ..classes import Context, Task
from ..classes import Book, Chapter, Episode
from .base import BaseTranslator


__all__ = ["GeminiTranslator"]


class GeminiTranslator(BaseTranslator):
    """
    # GeminiTranslator Class
    """
    name: str = Field(default_factory=lambda: f"gemini-{str(uuid4())[:8]}")
    description: str = "A translator for gemini.com"
    max_retries: int | None = 10
    """Max retries before giving up"""
    batch_size: int = 1024
    """Max characters to send in one batch"""
    max_tokens: int | None = None
    """Max tokens to preserve"""
    remind_interval: int | None = 3
    """Interval to remind glossaries"""
    skip_translated: bool = True
    """Skip already translated lines"""
    convert_ruby: bool = True
    """Convert <ruby> tags to simpler format for LLMs"""
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

        if episode.fully_translated and self.skip_translated:
            return episode

        cli = ctx.client
        self.backend._cli = cli
        db = ctx.db
        sauce_lang = LANG_NAME_TABLE.get(task.sauce_lang.upper(), task.sauce_lang)
        target_lang = LANG_NAME_TABLE.get(task.target_lang.upper(), task.target_lang)
        logger = ctx.logger
        sess = task.extra.get(self.name, self.backend.new_session())
        task.extra[self.name] = sess
        sess.message_lock = 2  # Prevents first 2 prompts being deleted

        prompt = (
            "You're a professional translator, "
            f"converting text from {sauce_lang} to {target_lang}. "
            "Correctly add missing subject and follow references. "
            f"Rephrase for {target_lang} naturalness and correct errors. "
            "For JSON, maintain keys with translated values. "
            "Strictly keep output lines count the same and preserve [](^) and [](*) if presented. "
            "Good translation examples for Japanese to Chinese:\n"
            "西に傾きかかった太陽は、この丘の裾遠く広がった有明の入り江の上に、長く曲折しつつはるか水平線の両端に消え入る白い沙丘の上に今は力なく其の光を投げていた。\n"
            "西斜的太阳，无力地照射着山脚下向远处扩展的有明海海湾，照射着蜿蜒曲折地消失在海平线远方的白色沙丘。\n"
            "事故が起こらないように、十分運転にお気を付けてください。\n"
            "请注意安全驾驶，以免发生事故。\n"
            "事件の詳しい経過がわかり次第、番組の中でお手伝えいたします。\n"
            "一旦弄清事情的详细经过，我们将随时在节目中报道。\n"
            # "並んでいるね。\n"
            # "这么多人排队啊。\n"
            "彼の言うことは、あるいは本当かもしれない。\n"
            "他说的或许是真的。\n"
            "「きみ、あたまいいね。」「よく言われるんだよ。」\n"
            "“你很聪明嘛！”“大家都这么说。”\n"
            "周囲を完全に包囲したから、犯人はもう袋のねずみだ。\n"
            "四下里都包围得如铁桶一般，这下他可是插翅难飞了。\n"
            # "我々は金大郎飴のように同じような車を作るつもりはない。\n"
            # "我们不打算生产过于雷同的车型。\n"
            "「いつか作家になるか、起業して楽しく暮らす」という夢を持っていた。\n"
            "我曾有个梦想，当个作家，或是自己做个小生意，过上幸福的生活。\n"
        )
        ex_prompt = prompt
        if task.glossaries:
            ex_prompt += "Translation reference you must follow:\n"
            ex_prompt += '\n'.join(f"{k} : {v}" for k, v in task.glossaries)
        if book is not None:
            ex_prompt += "\nThe book you are translating:\n"
            book_full_meta = {
                "title": book.title,
                "description": book.description,
                "series": book.series,
                "tags": list(book.tags),
            }
            ex_prompt += f"{json.dumps(book_full_meta, ensure_ascii=False)}\n"

        ex_prompt += "\nThe episode you are translating:\n"
        episode_meta: dict[str, str | None] = {
            "title": episode.title,
            "notes": episode.notes,
        }
        ex_prompt += f"{json.dumps(episode_meta, ensure_ascii=False)}\n"
        ex_prompt += (
            "\nYou can start translating now: {\"test_en\": \"りんごはおいしい！\", \"test_zh\": \"りんごはおいしい！\"")

        logger.debug("%s: generated prompt: %s", self, ex_prompt)

        sess.append(Message(role=Role.User, parts=ex_prompt))
        sess.append(Message(role=Role.Model,
                    parts="{\"test_en\": \"Apple is yummy!, \"test_zh\": \"苹果很好吃！\""))

        def remind():
            logger.debug("%s: Sending reminder", self)
            sess.append(
                Message(role=Role.User, parts=f"{prompt}\nTranslation references [{", ".join(g[0] for g in task.glossaries)}]"))
            sess.append(
                Message(role=Role.Model, parts=f"[{", ".join(g[1] for g in task.glossaries)}]"))
        remind()
        cycle = 0

        @overload
        async def translate(c: dict[str, str | None]) -> dict[str, str | None]:
            ...

        @overload
        async def translate(c: list[str]) -> list[str]:
            ...

        async def translate(
                c: list[str] | dict[str, str | None]
        ) -> list[str] | dict[str, str | None]:
            nonlocal cycle
            if isinstance(c, dict):
                pstr = json.dumps(c, ensure_ascii=False)
            else:
                pstr = '\n'.join(map(lambda x: x.replace('\n', r"\n"), c))

            # Gemini API mistreats some repititions as errors
            # manually encode repetitions to avoid this
            pstr = escape_repetition(pstr)

            if self.convert_ruby:
                pstr = escape_ruby(pstr)

            logger.debug("%s: Sending prompt: %s", self, pstr)
            await sess.trim(self.max_tokens)
            sess_bak = sess.messages.copy()

            retry = 0

            while True:
                resp: str = "None"
                try:
                    resp = await sess.send(pstr)

                    if self.convert_ruby:
                        resp = unescape_ruby(resp)

                    resp = unescape_repetition(resp)

                    logger.debug("%s: Received response: %s", self, resp)
                    if isinstance(c, list):
                        obj = resp.split('\n')
                        obj = list(
                            filter(None, map(lambda x: x.replace(r"\n", '\n'), obj)))
                        if not isinstance(obj, list):
                            raise TypeError("Expected list, got dict")
                        if len(obj) != len(c):
                            raise ValueError("Length mismatch")
                    else:
                        obj = json.loads(resp)
                        if not isinstance(obj, dict):
                            raise TypeError("Expected dict, got list")
                        if obj.keys() != c.keys():
                            raise ValueError("Key mismatch")

                    return obj

                except ContentBlockedError as e:
                    raise

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

                finally:
                    cycle += 1
                    if self.remind_interval is not None and cycle >= self.remind_interval:
                        remind()
                        cycle = 0

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
            chapter_meta: dict[str, str | None] = {
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
                    line = episode.lines[j]
                    line.translated = v
                    line.candidates[self.name] = v
                    if not v.strip():
                        logger.warning("%s: Empty translation for %s", self, o)
                indexes.clear()
                contents.clear()
                c_cnt = 0

        if indexes:
            translated = await translate(contents)
            for j, v in zip(indexes, translated):
                line = episode.lines[j]
                line.translated = v
                line.candidates[self.name] = v
                if not v.strip():
                    logger.warning("%s: Empty translation for %s", self, o)

        q = Query()
        if book is not None:
            await db.upsert(book.model_dump(mode="json"),
                            (q.title == book.title) & (q.author == book.author))

        return episode
