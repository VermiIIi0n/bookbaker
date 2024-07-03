from __future__ import annotations

import re
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


__all__ = ["NovelUpCrawler"]


class NovelUpCrawler(BaseCrawler):
    """
    Crawler for novelup.plus
    """
    name: str = Field(default_factory=lambda: f"novelup-{str(uuid4())[:8]}")
    description: str = "A crawler for novelup.plus"

    _dt_re = re.compile(r".*?(\d+)\D(\d{1,2})\D(\d{1,2})\D+(\d{1,2})\D(\d{1,2}).*")
    _ep_ord_re = re.compile(r"^(\d+)")

    async def crawl_stream(
            self,
            task: Task,
            ctx: Context,
    ):
        logger = ctx.logger
        db = ctx.db
        cli = ctx.client
        url = urlparse(task.url)
        origin = f"{url.scheme}://{url.netloc}"
        logger.info("%s: Crawling URL %s", self, task.url)
        r = await cli.get(task.url)
        r.raise_for_status()

        soup = bs4.BeautifulSoup(r.text.replace('\u3000', "  "), "xml")
        body = soup.body
        title = body.find(class_="novel_title").text.strip()
        author = body.find(class_="novel_author").a.text.strip()
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

        desc = body.find(class_="novel_synopsis")
        for br in desc.find_all('br'):
            br.replace_with(f"\n{br.text}")
        book.description = desc.text.strip()

        info_div = body.find(id="section_episode_info_table")
        info_tab = info_div.find("table")
        for tr in info_tab.find_all("tr"):
            if "ジャンル" in tr.th.text:
                genres = tr.td.text.strip().split()
                book.tags.update(genres)
            elif "タグ" in tr.th.text:
                tags = tr.td.text.strip().split()
                book.tags.update(tags)
            elif "セルフレイティング" in tr.th.text:
                ratings = tr.td.text
                if "残酷描写" in ratings:
                    book.tags.add("残酷描写")
                if "暴力描写" in ratings:
                    book.tags.add("暴力描写")
                if "性的表現" in ratings:
                    book.tags.add("性的表現")
            elif "初掲載日" in tr.th.text:
                book.time_meta.created_at = self._parse_datatime(tr.td.text)
            elif "最終更新日" in tr.th.text:
                book.time_meta.updated_at = self._parse_datatime(tr.td.text)

        indexes = body.find(class_="episode_list")
        default_chapter = book.get_chapter('')

        if default_chapter is None:
            default_chapter = Chapter(title='')
            book.chapters.append(default_chapter)
        chapter = default_chapter

        for child in indexes.find_all("li"):
            if not isinstance(child, bs4.Tag):
                continue
            if "chapter" in child["class"]:
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
                div = child.find("div")
                episode_url = cast(str, div.a["href"])
                if episode_url.startswith("/"):
                    episode_url = f"{origin}{episode_url}"

                subtitle = div.text.strip()
                subtitle = self._ep_ord_re.sub(
                    '', subtitle).strip()  # remove episode number
                logger.info("%s: Crawling episode %s from %s",
                            self, subtitle, episode_url)

                dates = child.find(class_="update_date")
                created_at = self._parse_datatime(
                    dates.find("span").text.replace('\n', ' '))
                updated_at = created_at
                next_span = dates.find_next_sibling("span")
                if next_span:
                    updated_at = self._parse_datatime(
                        next_span.text.replace('\n', ' '))

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
                                (book_query.title == title) & (book_query.author == author))

                yield task, book, chapter, episode

        if not default_chapter.episodes:
            book.chapters.remove(default_chapter)

        await db.upsert(book.model_dump(mode="json"),
                        (book_query.title == title) & (book_query.author == author))

    def _parse_datatime(self, dt: str) -> datetime:
        try:
            dts = self._dt_re.match(dt)
            if dts is None:
                raise ValueError(f"Failed to parse datetime: {dt}")
            year, month, day, hour, minute = map(int, dts.groups())
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
        r = await client.get(url, cookies={"over18": "yes"})
        r.raise_for_status()

        if created_at is not None:
            created_at = created_at.astimezone(UTC)
        if updated_at is not None:
            updated_at = updated_at.astimezone(UTC)

        soup = bs4.BeautifulSoup(r.text.replace('\u3000', "  "), "xml")
        body = soup.body
        title = body.find(class_="episode_title").text.strip()
        honbun = body.find(id="episode_content")
        for br in honbun.find_all("br"):
            br: bs4.Tag
            br.replace_with(f"\n{br.decode_contents()}")

        lines = [Line(content=p) for p in honbun.text.splitlines()]

        episode = Episode(
            title=title,
            lines=lines,
            time_meta=TimeMeta(
                created_at=created_at, updated_at=updated_at),
        )
        preview = body.find(class_="novel_afterword")
        if preview:
            episode.notes = preview.text

        return episode
