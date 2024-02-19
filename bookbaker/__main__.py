import asyncio
import sys
import argparse
from typing import AsyncGenerator
import ujson as json
from pathlib import Path
from vermils.asynctools import select
from asynctinydb import Query
from bookbaker import Config, Context, Book, Chapter, Episode, Task
from bookbaker.roles import DeepLTranslator, SyosetuComCrawler, GeminiTranslator
from bookbaker.roles import EpubExporter, AutoCrawler, GPTTranslator
from bookbaker.roles import BaseRole, BaseCrawler, BaseTranslator, BaseExporter
from bookbaker.roles import recover_from_dict


async def main():
    # parser = argparse.ArgumentParser(
    #     prog="bookbaker",
    #     description="A light novel scraping and translating tool",
    # )
    # parser.add_argument(
    #     "action",
    #     type=str,
    #     choices=["crawl", "translate", "export"],
    #     help="Action to perform",
    # )

    # args = parser.parse_args()

    config_path = Path("config.json")
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
                translator="deepl",
                exporter="epub",
                glossaries=[
                    ["ザラキエル", "撒拉琪尔"],
                ]
            ))
            gmt = GeminiTranslator(name="gemini")
            gmt.backend.comp_tokens = 4096
            config.roles.append(gmt)
            gpt = GPTTranslator(name="gpt")
            gpt.backend.comp_tokens = 2048
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

    for t in config.tasks:
        crawler: BaseCrawler = AutoCrawler() if t.crawler is None else get_role(t.crawler)
        logger.info("Book %s (%s) added to crawl queue", t.friendly_name, t.url)
        streams.append(crawler.crawl_stream(
            t,
            ctx=ctx
        )
        )

    async for fut in select(streams, return_future=True):
        try:
            task, book, chapter, episode = fut.result()

            if task.translator is None:
                continue

            translator: BaseTranslator = get_role(task.translator)

            if not episode.fully_translated:
                try:
                    await translator.translate(
                        episode,
                        task,
                        ctx,
                        chapter=chapter,
                        book=book,
                    )
                except KeyboardInterrupt:
                    logger.info("Interrupted by user")
                    continue
            else:
                logger.info("Episode %s is already fully translated", episode.title)

        except Exception as e:
            logger.critical("Failed to process: %s due to %s", task.url, e)
            logger.exception(e)

    q = Query()
    for task in config.tasks:
        if task.exporter is None:
            continue
        exporter: BaseExporter = get_role(task.exporter)
        data = await ctx.db.get(q.url == task.url)
        if not data:
            logger.critical("%s: No data found for %s", exporter, task.url)
            continue
        book = Book.model_validate(data)
        try:
            data = await exporter.export(book, task, ctx)
        except Exception as e:
            logger.critical("%s: Failed to export book %s", exporter, book.title)
            logger.exception(e)

    logger.info("Closing...")
    await db.close()

sys.exit(asyncio.run(main()))
