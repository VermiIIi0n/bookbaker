from __future__ import annotations

from uuid import uuid4
from pydantic import Field
from asynctinydb import Query
from aiodeepl import Translator
from .base import BaseTranslator
from ..classes import Book, Chapter, Episode, Task, Context


__all__ = ["DeepLTranslator"]


class DeepLTranslator(BaseTranslator):
    """
    # DeepLTranslator Class
    """
    name: str = Field(default_factory=lambda: f"deepl-{str(uuid4())[:8]}")
    description: str = "DeepL Translator"
    skip_translated: bool = True
    backend: Translator = Field(
        default_factory=lambda: Translator(api_key=''))

    async def translate(
            self,
            episode: Episode,
            task: Task,
            ctx: Context,
            chapter: Chapter | None = None,
            book: Book | None = None,
    ) -> Episode:
        logger = ctx.logger
        logger.info("%s: Translating episode %s", self, episode.title)
        indexes = list[int]()
        contents = list[str]()
        glossaries = task.glossaries
        sauce_lang = task.sauce_lang
        target_lang = task.target_lang
        for i, line in enumerate(episode.lines):
            if not line.content.strip():
                continue  # skip empty lines
            if self.skip_translated and line.translated is not None:
                continue
            indexes.append(i)
            contents.append(line.content)
        if not indexes:
            logger.info("%s: Episode %s is fully translated", self, episode.title)
            return episode
        logger.info("%s translating %d lines", self, len(indexes))
        context = ''
        if book is not None:
            context += f"Book title: {book.title}\n"
            if book.description:
                context += f"Book description: {book.description}\n"
            if book.tags:
                context += f"Book tags: {','.join(book.tags)}\n"
        if chapter is not None:
            context += f"Chapter title: {chapter.title}\n"
        if episode.title:
            context += f"Episode title: {episode.title}\n"
        gid: str | None = None
        if glossaries:
            pairs = await self.backend.glossary_available_pairs()
            if (sauce_lang, target_lang) in pairs:
                logger.debug("%s: Glossary pair uploading", self)
                gid = (await self.backend.glossary_create(
                    f"glossary-{str(uuid4())[:8]}",
                    sauce_lang,
                    target_lang,
                    entries=glossaries,
                )).glossary_id
            else:
                logger.warning("%s: Glossary pair %s-%s not available",
                               self, sauce_lang, target_lang)

        try:
            async def translate(c: list[str] | str):
                return await self.backend.translate(
                    c,
                    target_lang=target_lang,
                    source_lang=sauce_lang,
                    context=context,
                    split_sentences='0',
                    preserve_formatting=True,
                    tagged_handling="html",
                    glossary_id=gid,
                )

            if book is not None:
                if book.title and (book.title_translated is None or not self.skip_translated):
                    book.title_translated = (await translate(book.title)).text
                if book.description and (book.description_translated is None or not self.skip_translated):
                    book.description_translated = (await translate(book.description)).text
                if book.series and (book.series_translated is None or not self.skip_translated):
                    book.series_translated = (await translate(book.series)).text

            if ((chapter is not None and chapter.title)
                    and (chapter.title_translated is None or not self.skip_translated)):
                chapter.title_translated = (await translate(chapter.title)).text

            if episode.title and (episode.title_translated is None or not self.skip_translated):
                episode.title_translated = (await translate(episode.title)).text
            if episode.notes and (episode.notes_translated is None or not self.skip_translated):
                episode.notes_translated = (await translate(episode.notes)).text

            translated = await translate(contents)

            for i, t in zip(indexes, translated):
                logger.debug("%s %s -> %s", self, episode.lines[i].content, t.text)
                episode.lines[i].translated = t.text
                episode.lines[i].candidates[self.name] = t.text
                if not t.text.strip():
                    logger.warning("%s: Empty translation for line %s in episode %s",
                                   self, episode.lines[i].content, episode.title)

            logger.info("%s: Translated episode %s", self, episode.title)

            if book is not None:
                logger.debug("%s: Upserting book %s", self, book.title)
                q = Query()
                await ctx.db.upsert(book.model_dump(mode="json"),
                                    q.title == book.title and q.author == book.author)
            return episode
        finally:
            if gid:
                await self.backend.glossary_delete(gid)
