from __future__ import annotations

import bs4
import httpx
from typing import cast
from uuid import uuid4
from pydantic import Field
from asynctinydb import Query, Document
from datetime import datetime, UTC
from urllib.parse import urlparse
from .base import BaseCrawler
from ..classes import Book, Chapter, Episode, Line, TimeMeta, Context, Task


__all__ = ["SyosetuOrgCrawler"]


class SyosetuOrgCrawler(BaseCrawler):
    """
    Crawler for syosetu.org
    """
    name: str = Field(default_factory=lambda: f"syosetu-org-{str(uuid4())[:8]}")
    description: str = "A crawler for syosetu.org"

    async def crawl_stream(
            self,
            task: Task,
            ctx: Context,
    ):
        logger = ctx.logger
        db = ctx.db
        cli = ctx.client
        url = urlparse(task.url)
        logger.info("%s: Crawling URL %s", self, task.url)
        r = await cli.get(task.url)
        r.raise_for_status()

        soup = bs4.BeautifulSoup(r.text.replace('\u3000', "  "), "lxml")
        body = soup.body
        title = body.find(itemprop="name").text.strip()
        author = body.find(itemprop="author").text.strip()
        logger.info("%s: Crawling book %s by %s", self, title, author)

        book_query = Query()
        data: Document = await db.get(
            (book_query.title == title) & (book_query.author == author))
        if data:
            logger.debug("%s: Book %s retrieved from database", self, title)
            book = Book.model_validate(dict(data))
        else:
            book = Book(title=title, author=author)

        book.url = task.url

        tags = set[str]()
        genre = body.find(itemprop="genre")
        for child in genre.children:
            if not isinstance(child, bs4.Tag):
                continue
            tags.add(child.text.strip())
        for tag in body.find_all('a', class_="alert_color"):
            tag: bs4.Tag
            tags.add(tag.text.strip())
        for tag in body.find_all(itemprop="keywords"):
            tags.add(tag.text.strip())
        book.tags.update(tags)

        maind = body.find(id="maind")
        divs = maind.find_all("div")
        desc_div = divs[2]
        desc = ''
        for br in desc_div.find_all('br'):
            br.replace_with(f"\n{br.text}")
        for child in desc_div.children:
            if isinstance(child, bs4.NavigableString):
                desc += str(child)
        book.description = desc

        indexes = maind.find("table")
        default_chapter = book.get_chapter('')

        if default_chapter is None:
            default_chapter = Chapter(title='')
            book.chapters.append(default_chapter)
        chapter = default_chapter

        for child in indexes.find_all("tr"):
            child: bs4.Tag
            if len(child.find_all("td")) == 1:
                chapter_name = child.text.strip()
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
            else:
                tds = list[bs4.Tag](child.find_all("td"))
                episode_url = cast(str, tds[0].a["href"])
                if episode_url.startswith("./"):
                    path = url.path.removesuffix("/")
                    path += episode_url[1:]
                    episode_url = f"{url.scheme}://{url.netloc}{path}"

                subtitle = tds[0].text.strip()
                logger.info("%s: Crawling episode %s from %s",
                            self, subtitle, episode_url)

                created_at = self._parse_datatime(
                    tds[1].text.strip()
                )
                updates = tds[1].find_all("span")
                updated_at = self._parse_datatime(
                    updates[-1]["title"]) if updates else created_at

                episode = chapter.get_episode(subtitle)
                if episode is not None:
                    logger.debug("%s: Episode %s retrieved from database",
                                 self, subtitle)
                    if episode.time_meta.created_at is None:
                        episode.time_meta.created_at = created_at
                    episode.time_meta.updated_at = updated_at
                    created_at = episode.time_meta.created_at

                    if episode.time_meta.saved_at < updated_at:
                        logger.debug("%s: Episode %s updated", self, subtitle)
                        episode_index = chapter.episodes.index(episode)
                        episode = await self.get_episode(
                            episode_url, cli,
                            created_at=created_at, updated_at=updated_at)
                        chapter.episodes[episode_index] = episode
                else:
                    logger.debug("%s: New episode %s created", self, subtitle)
                    episode = await self.get_episode(
                        episode_url, cli,
                        created_at=created_at, updated_at=updated_at)
                    chapter.episodes.append(episode)

                if not episode.lines:
                    logger.warning("%s: Episode %s has no content", self, subtitle)

                await db.upsert(book.model_dump(mode="json"),
                                book_query.title == title
                                and book_query.author == author)

                yield task, book, chapter, episode

        if not default_chapter.episodes:
            book.chapters.remove(default_chapter)

        await db.upsert(book.model_dump(mode="json"),
                        (book_query.title == title) & (book_query.author == author))

    def _parse_datatime(self, dt: str) -> datetime:
        """e.g. '2024年01月16日(火) 22:08改稿'"""
        try:
            dt = dt.strip()
            year, month, day, hour, minute = map(int, (
                dt[:4], dt[5:7], dt[8:10], dt[15:17], dt[18:20])
            )
            return datetime(
                year=year, month=month, day=day, hour=hour, minute=minute
            ).astimezone(UTC)
        except Exception as e:
            raise ValueError(f"Failed to parse datetime: {dt}") from e

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
        title = soup.find(
            "meta", property="og:title")["content"].split(" - ", maxsplit=2)[0]

        honbun = body.find(id="honbun")
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
        preview = body.find(id="maegaki")
        if preview:
            for br in preview.find_all("br"):
                br: bs4.Tag
                br.replace_with(f"\n{br.decode_contents()}")
            episode.notes = preview.text

        return episode
