from __future__ import annotations

import re
from uuid import uuid4
from io import BytesIO
from pathlib import Path
from ebooklib import epub
from pydantic import Field
from base64 import b64decode, b64encode
from vermils.io import aio
from ..classes import Book, Context, Chapter, Episode, Task
from ..utils import get_url_content
from .base import BaseExporter


_a_img_matcher = re.compile(
    r"<a.*?href=\"(.+\.(?:png|jpg|jpeg|webp|gif|PNG|JPG|JPEG|WEBP|GIF))\".*?>.*?<\/a>")
_img_matcher = re.compile(r"<img.*?src=\"(.*?)\".*?>")


class EpubExporter(BaseExporter):
    """
    Exporter for EPUB
    """
    name: str = Field(default_factory=lambda: f"epub-{str(uuid4())[:8]}")
    description: str = "EPUB Exporter"

    async def export(
            self,
            book: Book,
            task: Task,
            ctx: Context,
    ) -> epub.EpubBook:
        logger = ctx.logger
        logger.info("%s: Exporting book %s", self, book.title)

        book_title = book.title_translated or book.title
        book_desc = book.description_translated or book.description
        lang = task.target_lang
        # if use_translated:
        #     book_title = book.title_translated or book.title
        #     book_desc = book.description_translated or book.description
        #     lang = task.target_lang
        # else:
        #     book_title = book.title
        #     book_desc = book.description
        #     lang = task.sauce_lang

        epub_book = epub.EpubBook()
        bid = str(hash((book.title, book.author)))
        epub_book.set_identifier(bid)
        epub_book.set_title(book_title)
        epub_book.set_language(lang)
        epub_book.add_author(book.author)

        if book.cover:
            cover_image: bytes | None = None
            try:
                cover_image = await get_url_content(book.cover.url, task.url, ctx)
                if cover_image:
                    epub_book.set_cover(file_name=book.cover.url, content=cover_image)
            except Exception as e:
                logger.warning(
                    "%s: Failed to set cover image for book: %s", self, book.title)
                logger.exception(e)

        for tag in book.tags:
            epub_book.add_metadata('DC', 'subject', tag)

        if book_desc:
            epub_chapter = epub.EpubHtml(title="Introduction", content=f"<p>{
                                         book_desc}</p>", file_name="intro.xhtml")
            epub_book.add_item(epub_chapter)
            epub_book.toc.append(epub_chapter)

        for chapter in book.chapters:
            epub_chapter = epub.EpubHtml(
                title=chapter.title_translated or chapter.title,
                file_name=f"{chapter.title}.xhtml",
            )
            epub_chapter.content = f"<h1>{chapter.title}</h1>"
            if chapter.cover:
                cover_image: bytes | None = None
                try:
                    cover_image = await get_url_content(chapter.cover.url, task.url, ctx)
                    epub_chapter.add_item(epub.EpubImage(
                        file_name=chapter.cover.url,
                        content=cover_image,
                        media_type="image/*"))
                except Exception as e:
                    logger.warning(
                        "%s: Failed to set cover image for chapter: %s", self, chapter.title)
                    logger.exception(e)
            epub_book.add_item(epub_chapter)
            # epub_book.toc.append(epub_chapter)
            for episode in chapter.episodes:
                episode_title = episode.title_translated or episode.title
                epub_chapter = epub.EpubHtml(
                    title=episode_title, file_name=f"{episode_title}.xhtml")
                episode_html = episode.html

                # Convert <a> tags pointing to images to <img> tags
                for match in _a_img_matcher.finditer(episode_html):
                    logger.debug("%s: Converting <a> tag to <img> tag: %s",
                                 self, match.group(0))
                    img_src = match.group(1)
                    episode_html = episode_html.replace(
                        match.group(0), f"<img src=\"{img_src}\" />")

                # Try to replace <img> tags with base64 encoded images
                for match in _img_matcher.finditer(episode_html):
                    img_src = match.group(1)
                    try:
                        logger.debug(
                            "%s: Converting image to base64: %s", self, img_src)
                        img_content = await get_url_content(img_src, task.url, ctx)
                        img_content = b64encode(img_content)
                        img_src = f"data:image/*;base64,{img_content.decode()}"
                        episode_html = episode_html.replace(
                            match.group(0), f"<img src=\"{img_src}\" />")
                    except Exception as e:
                        logger.warning(
                            "%s: Failed to convert image to base64: %s", self, img_src)
                        logger.exception(e)

                epub_chapter.content = episode_html
                epub_book.add_item(epub_chapter)
                epub_book.toc.append(epub_chapter)

        epub_book.add_item(epub.EpubNcx())
        epub_book.add_item(epub.EpubNav())
        epub_book.spine = ['nav'] + epub_book.toc

        if not await aio.path.exists("exports"):
            await aio.os.mkdir("exports")
        path = "exports" / Path(f"{book.title}.epub")

        ebook_bytes = BytesIO()
        epub.write_epub(ebook_bytes, epub_book, {})
        ebook_bytes.seek(0)

        async with aio.open(str(path), "wb") as f:
            await f.write(ebook_bytes.getvalue())

        return epub_book

    # async def convert(
    #         self,
    #         book: Book,
    #         task: Task,
    #         ctx: Context,
    # ) -> epub.EpubBook:
    #     logger = ctx.logger
