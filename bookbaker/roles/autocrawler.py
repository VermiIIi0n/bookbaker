from __future__ import annotations

from uuid import uuid4
from pydantic import Field
from urllib.parse import urlparse
from .base import BaseCrawler
from .syosetu_com import SyosetuComCrawler
from .syosetu_org import SyosetuOrgCrawler
from .kakuyomu import KakuyomuCrawler
from .novelup import NovelUpCrawler
from ..classes import Context, Task


__all__ = ["AutoCrawler"]


class AutoCrawler(BaseCrawler):
    """
    Automatically choose the right crawler for the given URL
    """
    name: str = Field(default_factory=lambda: f"auto-{str(uuid4())[:8]}")
    description: str = "Automatically choose crawler to use"

    def crawl_stream(
            self,
            task: Task,
            ctx: Context,
    ):
        url = urlparse(task.url)
        hostname = url.hostname
        crawler: BaseCrawler
        if hostname is None:
            raise ValueError(f"Invalid URL: {task.url}")
        if hostname.endswith("syosetu.com"):
            crawler = SyosetuComCrawler()
        elif hostname.endswith("syosetu.org"):
            crawler = SyosetuOrgCrawler()
        elif hostname.endswith("kakuyomu.jp"):
            crawler = KakuyomuCrawler()
        elif hostname.endswith("novelup.plus"):
            crawler = NovelUpCrawler()
        else:
            raise ValueError(f"Cannot determine the crawler for {task.url}")

        return crawler.crawl_stream(task, ctx)
