import asyncio
import sys
import argparse
from typing import AsyncGenerator, Literal
import ujson as json
from pathlib import Path
from vermils.asynctools import select
from asynctinydb import Query
from bookbaker import Config, Context, Book, Chapter, Episode, Task
from bookbaker.roles import DeepLTranslator, SyosetuComCrawler, GeminiTranslator
from bookbaker.roles import EpubExporter, AutoCrawler, GPTTranslator
from bookbaker.roles import BaseRole, BaseCrawler, BaseTranslator, BaseExporter
from bookbaker.roles import recover_from_dict


async def main() -> int:
    parser = argparse.ArgumentParser(
        prog="bookbaker",
        description="A light novel scraping and translating tool",
    )
    parser.add_argument(
        "action",
        type=str,
        choices=["crawl", "translate", "export", "all"],
        help=(
            "Action to perform\n"
            "crawl: Just crawl\n"
            "translate: Crawl and translate\n"
            "export: Just export\n"
            "all: Crawl, translate and export"
        ),
        default="all",
        nargs="?",
    )
    parser.add_argument("-c", "--config", type=str,
                        help="Path to config file", default="config.json")

    args = parser.parse_args()

    action: Literal["crawl", "translate", "export", "all"] = args.action
    config_path = Path(args.config)
    if not config_path.exists():
        print("Config file not found")
        user_input = input("Create a new config file? (Y/n): ").strip() or 'y'
        if user_input.lower() == 'y':
            config = Config()
            config.tasks.append(Task(
                url="https://syosetu.org/novel/333942/",
                friendly_name="sample - TS Tenshi",
                sauce_lang="JA",
                target_lang="ZH",
                crawler=None,
                translator=["gemini", "gpt"],
                exporter="epub",
                glossaries=[
                    ["ザラキエル", "萨拉琪尔"],
                    ["神専魔法", "神专魔法"],
                    ["サーヴィトリ", "萨维特丽"],
                    ["サラフィエル", "萨拉菲尔"],
                    ["アルマロス", "阿尔马洛斯"],
                    ["クロ", "小黑"]
                ]
            ))
            gmt = GeminiTranslator(name="gemini")
            gmt.backend.comp_tokens = 4096
            gmt.backend.temperature = 0.5
            config.roles.append(gmt)
            gpt = GPTTranslator(name="gpt")
            gpt.backend.comp_tokens = 2048
            gpt.backend.temperature = 0.4
            config.roles.append(gpt)
            config.roles.append(SyosetuComCrawler(name="syosetu-com"))
            config.roles.append(DeepLTranslator(name="deepl"))
            config.roles.append(EpubExporter(name="epub"))
            config_path.write_text(
                json.dumps(
                    config.model_dump(mode="json"),
                    indent=2,
                    ensure_ascii=False,
                ))
            print(f"Config file created at {config_path}")
            return 0
        else:
            return 2

    config = Config.model_validate_json(config_path.read_text())

    db = config.db.get_db()
    client = config.client.get_cli()
    logger = config.logging.get_logger()
    roles: list[BaseRole] = [recover_from_dict(d) for d in config.roles]

    def get_role(name: str):
        for role in roles:
            if role.name == name:
                return role
        raise ValueError(f"Role {name} not found")

    ctx = Context(
        db=db,
        client=client,
        logger=logger,
    )

    streams = list[AsyncGenerator[
        tuple[Task, Book, Chapter, Episode], None]]()

    async def crawl(crawler: BaseCrawler, t: Task, ctx: Context):
        async with t.lock:
            async for c in crawler.crawl_stream(t, ctx):
                t.lock.release()
                yield c
                await t.lock.acquire()

    if action in ("crawl", "translate", "all"):
        for t in config.tasks:
            crawler: BaseCrawler = AutoCrawler() if t.crawler is None else get_role(t.crawler)
            logger.info("Book %s (%s) added to crawl queue", t.friendly_name, t.url)
            streams.append(crawl(
                crawler,
                t,
                ctx=ctx
            ))

    async def translate(task: Task, book: Book, chapter: Chapter, episode: Episode):
        if (task.translator is None
                or task.translator == []
                or action not in ("translate", "all")):
            return
        async with task.lock:
            translators = list[BaseTranslator](
                [get_role(task.translator)]
                if isinstance(task.translator, str)
                else [get_role(t) for t in task.translator]
            )
            for translator in translators:
                logger.info("Translating %s with %s", episode.title, translator)

                try:
                    episode = await translator.translate(
                        episode,
                        task,
                        ctx,
                        chapter=chapter,
                        book=book,
                    )
                except Exception as e:
                    logger.exception(e)
                    if translator is translators[-1]:
                        logger.critical(
                            "Failed to translate %s with the last translator %s",
                            episode.title, translator)
                    else:
                        logger.warning("Failed to translate %s with %s",
                                       episode.title, translator)

    loop = asyncio.get_running_loop()
    aiotasks = list[asyncio.Task]()

    async for fut in select(streams, return_future=True):
        try:
            task, book, chapter, episode = fut.result()
        except Exception as e:
            logger.critical("Failed to crawl a url due to %s", e)
            logger.exception(e)
            continue

        aiotasks.append(loop.create_task(translate(task, book, chapter, episode)))

    await asyncio.gather(*aiotasks)

    if action in ("export", "all"):
        q = Query()
        for task in config.tasks:
            if task.exporter is None:
                continue
            exporters: list[BaseExporter] = (
                [get_role(task.exporter)]
                if isinstance(task.exporter, str)
                else [get_role(e) for e in task.exporter]
            )

            data = await ctx.db.get(q.url == task.url)
            if not data:
                logger.critical("No exporting data found for %s", task.url)
                continue
            book = Book.model_validate(data)

            for exporter in exporters:
                try:
                    logger.info("Exporting %s with %s", book.title, exporter)
                    data = await exporter.export(book, task, ctx)
                except Exception as e:
                    logger.critical("%s: Failed to export book %s",
                                    exporter, book.title)
                    logger.exception(e)

    logger.info("Closing...")
    await db.close()

    return 0

sys.exit(asyncio.run(main()))
