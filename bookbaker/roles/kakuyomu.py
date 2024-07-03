from __future__ import annotations

import bs4
import httpx
import ujson as json
from typing import Any
from uuid import uuid4
from pydantic import Field
from asynctinydb import Query, Document
from datetime import datetime, UTC
from urllib.parse import urlparse
from .base import BaseCrawler
from ..classes import Book, Chapter, Episode, Line
from ..classes import TimeMeta, Context, Task, ImageRef


__all__ = ["KakuyomuCrawler"]


class KakuyomuCrawler(BaseCrawler):
    """
    Crawler for kakuyomu.jp
    """
    name: str = Field(default_factory=lambda: f"kakuyomu-{str(uuid4())[:8]}")
    description: str = "A crawler for kakuyomu.jp"

    async def crawl_stream(
            self,
            task: Task,
            ctx: Context,
    ):
        logger = ctx.logger
        db = ctx.db
        cli = ctx.client
        url = urlparse(task.url)
        url_path = url.path.removesuffix('/')
        origin = f"{url.scheme}://{url.netloc}"
        logger.info("%s: Crawling URL %s", self, task.url)
        r = await cli.get(task.url)
        r.raise_for_status()

        soup = bs4.BeautifulSoup(r.text.replace('\u3000', "  "), "lxml")
        data = json.loads(soup.find(id="__NEXT_DATA__").text)
        items = data["props"]["pageProps"]["__APOLLO_STATE__"]
        work_info: dict[str, Any] = items[f"Work:{url_path.removeprefix("/works/")}"]
        title: str = work_info["title"]
        author = items[work_info["author"]["__ref"]]["name"]

        logger.info("%s:  book %s by %s", self, title, author)
        book_query = Query()
        data: Document = await db.get(
            (book_query.title == title) & (book_query.author == author))
        if data:
            logger.debug("%s: Book %s retrieved from database", self, title)
            book = Book.model_validate(dict(data))
        else:
            book = Book(title=title, author=author)

        book.url = task.url

        cover = work_info["adminCoverImageUrl"]
        if cover is None:
            logger.info("%s: No cover found for %s", self, title)
        else:
            book.cover = ImageRef(url=cover["content"])

        desc = work_info.get("catchphrase", '')
        desc += f"\n{work_info["introduction"]}"
        book.description = desc

        book.time_meta.created_at = datetime.fromisoformat(
            work_info["publishedAt"]).astimezone(UTC)
        book.time_meta.updated_at = datetime.fromisoformat(
            work_info.get("lastEpisodePublishedAt",
                          book.time_meta.created_at)).astimezone(UTC)
        book.tags.update(work_info["tagLabels"])
        if work_info["isCruel"]:
            book.tags.add("残酷描写")
        if work_info["isViolent"]:
            book.tags.add("暴力描写")
        if work_info["isSexual"]:
            book.tags.add("性描写")

        toc = [items[ref["__ref"]] for ref in work_info["tableOfContents"]]

        for chapter_info in toc:
            chapter_name = items[chapter_info["chapter"]["__ref"]]["title"]

            logger.info("%s: Crawling chapter %s", self, chapter_name)
            old_chapter = book.get_chapter(chapter_name)
            if old_chapter is None:
                logger.debug("%s: New chapter %s created", self, chapter_name)
                chapter = Chapter(title=chapter_name)
                book.chapters.append(chapter)
            else:
                logger.debug("%s: Chapter %s retrieved from database",
                             self, chapter_name)
                chapter = old_chapter

            for episode_info in (items[ep["__ref"]] for ep in chapter_info["episodeUnions"]):

                episode_url = f"{
                    url.scheme}://{url.netloc}{url_path}/episodes/{episode_info["id"]}"

                subtitle = episode_info["title"]
                logger.info("%s: Crawling episode %s from %s",
                            self, subtitle, episode_url)

                published_at = datetime.fromisoformat(
                    episode_info["publishedAt"]).astimezone(UTC)
                created_at = published_at

                episode = chapter.get_episode(subtitle)
                if episode is not None:
                    logger.debug("%s: Episode %s retrieved from database",
                                 self, subtitle)
                    if episode.time_meta.created_at is None:
                        episode.time_meta.created_at = published_at
                    episode.time_meta.updated_at = published_at
                    created_at = episode.time_meta.created_at

                    if episode.time_meta.saved_at < published_at:
                        logger.debug("%s: Episode %s updated", self, subtitle)
                        episode_index = chapter.episodes.index(episode)
                        episode = await self.get_episode(
                            episode_url, cli,
                            created_at=created_at, updated_at=published_at)
                        chapter.episodes[episode_index] = episode
                else:
                    logger.debug("%s: New episode %s created", self, subtitle)
                    episode = await self.get_episode(
                        episode_url, cli,
                        created_at=created_at, updated_at=published_at)
                    chapter.episodes.append(episode)

                if not episode.lines:
                    logger.warning("%s: Episode %s has no content", self, subtitle)

                await db.upsert(book.model_dump(mode="json"),
                                (book_query.title == title) & (book_query.author == author))

                yield task, book, chapter, episode

        await db.upsert(book.model_dump(mode="json"),
                        (book_query.title == title) & (book_query.author == author))

    async def get_episode(
            self,
            url: str,
            client: httpx.AsyncClient,
            *,
            created_at: datetime | None = None,
            updated_at: datetime | None = None,
    ) -> Episode:
        r = await client.get(url)
        r.raise_for_status()

        if created_at is not None:
            created_at = created_at.astimezone(UTC)
        if updated_at is not None:
            updated_at = updated_at.astimezone(UTC)

        soup = bs4.BeautifulSoup(r.text.replace('\u3000', "  "), "lxml")
        body = soup.body
        title = body.find(class_="widget-episodeTitle").text.strip()
        honbun = body.find(class_="widget-episodeBody")
        lines = list[Line]()
        for p in honbun.find_all("p"):
            p: bs4.Tag
            for br in p.find_all("br"):
                br: bs4.Tag
                br.replace_with(f"\n{br.decode_contents()}")
            decoded = str(p.decode_contents())
            if not decoded.strip():
                decoded = ''  # replace empty lines with empty string
            lines.append(Line(content=decoded))

        episode = Episode(
            title=title,
            lines=lines,
            time_meta=TimeMeta(
                created_at=created_at, updated_at=updated_at),
        )

        return episode
