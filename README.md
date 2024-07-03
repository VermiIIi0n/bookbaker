# 焙书

## Introduction

自动化 爬取/翻译/导出 网页生肉书籍

你是否还在为：

1. 生肉无人烤
2. 译者咕咕
3. 翻译质量感人(虽然用爱发电伟大但是...)
4. 译文充满吐槽私货

而发愁？

随着 `Gemini AI` 和 `GPT4` 的推出，日文小说机器翻译的质量已经可以胜过某些人类了。

于是本库诞生来解救诸位。

本品特性：

1. 自带几个常见日轻爬虫，爬取网站文章
2. 支持 `DeepL`, `Gemini AI`, `ChatGPT`, `Sakura`(`GPT` 兼容) 等烤肉机
3. 支持导出至 `EPUB`, 自动发布至某些站点（未完工）
4. 自带小型 NoSQL 数据库，方便查看编辑
5. 模块化设计，方便自行定制爬虫，烤肉机，导出器
6. 自动在文章有更新时再爬取。

## NOTICE

**本品仍在 Beta 开发阶段，用量用法随时改变，效果随机出错，请自行斟酌。** 愿意测试者也许可以白嫖 `API Key` ? （数量有限不保证）

## Community

更多机翻内容和社区支持可移步[这里](https://books.fishhawk.top/)

## Installation

```bash
pip install -U bookbaker
```

或者想体验最新版可直接 clone 本库。

## Configuration

建议您切换至空目录下，然后运行 `bookbaker`, 这样将会在本目录下创建 `config.json` 。

以下为一个示例（示例内容可能更新不及时，仅供参考）：

<details>
  <summary>点我</summary>

```JSON {collapsed}
{
  "version": "1.0.0",
  "tasks": [
    {
      "friendly_name": "TS-Tenshi",
      "url": "https://syosetu.org/novel/333942/",
      "crawler": null,
      "translator": ["gemini", "gpt"],
      "exporter": "epub",
      "sauce_lang": "JA",
      "target_lang": "ZH",
      "glossaries": [
        ["ザラキエル", "萨拉琪尔"],
        ["神専魔法", "神专魔法"],
        ["サーヴィトリ", "萨维特丽"],
        ["サラフィエル", "萨拉菲尔"],
        ["アルマロス", "阿尔马洛斯"],
        ["クロ", "小黑"]
      ]
    }
  ],
  "roles": [
    {
      "name": "syosetu-com",
      "description": "A crawler for syosetu.com",
      "classname": "SyosetuComCrawler",
      "modulename": "bookbaker.roles.syosetu_com"
    },
    {
      "name": "deepl",
      "description": "DeepL Translator",
      "skip_translated": true,
      "backend": {
        "api_key": "",
        "use_pro": false,
        "free_host": "api-free.deepl.com",
        "pro_host": "api.deepl.com",
        "proxy": null,
        "retries": 3,
        "timeout": 10.0
      },
      "classname": "DeepLTranslator",
      "modulename": "bookbaker.roles.deepl"
    },
    {
      "name": "gemini",
      "description": "A translator for gemini.com",
      "max_retries": 10,
      "max_tokens": null,
      "remind_interval": 3,
      "skip_translated": false,
      "convert_ruby": true,
      "max_reply_tokens": null,
      "backend": {
        "model": "models\/gemini-pro",
        "api_key": "",
        "api_host": "generativelanguage.googleapis.com",
        "comp_tokens": 4096.0,
        "stop": null,
        "temperature": 0.5,
        "top_p": null,
        "top_k": null,
        "tools": null,
        "tool_choice": "auto",
        "safety_settings": [
          {
            "category": "HARM_CATEGORY_HARASSMENT",
            "threshold": "BLOCK_NONE",
            "probability": null
          },
          {
            "category": "HARM_CATEGORY_HATE_SPEECH",
            "threshold": "BLOCK_NONE",
            "probability": null
          },
          {
            "category": "HARM_CATEGORY_SEXUALLY_EXPLICIT",
            "threshold": "BLOCK_NONE",
            "probability": null
          },
          {
            "category": "HARM_CATEGORY_DANGEROUS_CONTENT",
            "threshold": "BLOCK_NONE",
            "probability": null
          }
        ],
        "proxy": null,
        "timeout": null
      },
      "classname": "GeminiTranslator",
      "modulename": "bookbaker.roles.gemini"
    },
    {
      "name": "epub",
      "description": "EPUB Exporter",
      "use_translated": true,
      "classname": "EpubExporter",
      "modulename": "bookbaker.roles.epub"
    }
  ],
  "client": {
    "user_agent": "Mozilla\/5.0 (X11; Linux x86_64) AppleWebKit\/537.36 (KHTML, like Gecko) Chrome\/121.0.0.0 Safari\/537.36",
    "timeout": 60.0,
    "proxy": null,
    "max_retries": 6,
    "trust_env": true
  },
  "db": {
    "path": "db.json",
    "write_buffer_size": 0
  },
  "logging": {
    "level": "DEBUG",
    "fmt": "%(asctime)s - %(levelname)s - %(message)s",
    "dirpath": "logs",
    "show_console": true
  }
}
```

</details>

### 配置各部分介绍

`tasks`

这部分定义了任务，一个任务就是要处理的书籍的相关信息。

- `friendly_name`: `str` 没啥用，助记的
- `url`: `str` 书籍的网址
- `crawler`: `str` 爬虫的名字，如果为 `null` 则会自动选择一个合适的爬虫
- `translator`: `str | list[str]` 翻译器的名字(们)，`null` 为不翻译。无负载均衡，只是按顺序前仆后继的翻译
- `exporter`: `str | list[str]` 导出器的名字(们)，`null` 为不导出，但年轻人导导更健康。多填时均会运行。
- `sauce_lang`: `str` 原文语言，`ISO 639` 格式
- `target_lang`: `str` 目标语言, `ISO 639` 格式
- `glossaries`: `list[tuple[str, str]]` 词汇表 例如 `[[Unacceptable, 可接受的], ...]`，可用于译名对照。

`roles`

这里定义了所有的 爬虫/烤肉机/导出器。他们的名字必须唯一。

`client`

共享的 `httpx.AsyncClient` 实例配置。

`db`

数据库配置。

- `path`: 数据库文件路径
- `write_buffer_size`: 写入缓冲区大小

`logging`

日志配置。

- `level`: 日志级别
- `fmt`: 日志格式
- `dirpath`: 日志文件夹路径
- `show_console`: 是否在控制台显示日志

### `roles` 再谈

以后也许会在这里补上自带模块的详细配置，现在因为开发阶段可能有诸多变化就先咕咕。

关于烤肉机的选择：

首先 `DeepL`/`Gemini AI`/`GPT` 都是基于变形金刚(~~完全胜利~~)的，所以他们共享一些特性。

`DeepL` 每个月免费用户有 500K 免费 `Tokens`，需要国外信用卡注册。但因为生成限制 `Tokens` 太短，一次性丢长句容易造成内容截断，所以是分句子发送的。这导致经常没有足够的语境提供信息，翻译的前后文会不搭调。~~但你就问快不快吧。~~ 另外对词汇表的语言组合有些限制。

`Gemini AI` 翻的最好，目前 `API` 价格便宜，速率限制不成问题，速度也不错。但一般用户无法解除所有`prompt` 安全限制后，得用月付账号（一个月$40K以上消费的公司可申请）或者填写这个[申请表格](https://docs.google.com/forms/d/e/1FAIpQLSeeaIrARA2Hdcri4upSNpS-OHnBEgzavVUpDhcVdWC_Qku_KQ/viewform?fbzx=-5066181756570666387)来解除限制，不然有些瑟瑟场面翻不了。另外比起 `GPT` 更容易偶尔摆烂直接吐原文，也不太尊重提供的词汇表。

`GPT` 家族翻译的还可以，风格有些过于严肃，流畅度和速度上不如 `Gemini`，`4.0` 的 `API` 收费，免费的速率限制基本也没法用，想交钱还得用美国本土信用卡，建议马家找中转。不愧是 `ClosedAI`。好在出错概率小，尊重词汇表，更能理解复杂的格式化(`HTML`/`JSON`/...)，内容安全限制更低 (这里倒是 Open 了是吧??)。

后两者的输出 Tokens 限制都在 2048-4096 左右，输入 Tokens 上万了，语境理解相当棒，一次也能吐很多内容 ~~只要你钱够~~。基本上能看的也就后俩的。但他俩翻久了容易忘记词汇表，如果遇到这问题可以降低他们配置中的 `reminder_interval` 来更频繁的提醒词汇表，建议适量。

| Name        | Speed    | Quality | Restriction | Cost     | Respect Glossaries  |
| ----------- | -------- | ------- | ----------- | -------- | ------------------- |
| `DeepL`     | VeryFast | Meh     | None        | Free/Low | Yes (when possible) |
| `Gemini AI` | Fast     | Good    | Some        | Free     | Not really          |
| `GPT`       | Slow     | Good    | Few         | High     | Yes                 |

## Baking

`config.json` 在生成时已有样例，按模板为你的 `config.json` 填入合适的任务，`api_key`。

切换到带有 `config.json` 的目录下，运行 `bookbaker` 即可。

导出的文件默认放到 `exports` 文件夹下

## 数据结构

数据库内有以下大致结构

数据库

- `Table`
  - `Books...`
    - `title`
    - `series`
    - `author`
    - `Tags...`： `list[str]`
    - ...
    - `Chapters...`:
      - `title`
      - ...
      - `Episodes...`
        - `title`
        - `notes`
        - `Lines...`
          - `content` 原文
          - `translated` 译文

主要内容都在各条 `Line` 中 `line.content`, `line.translated` 为原文和翻译文本。你可以自行修改。如果想要重新翻译某句话，可以直接将 `line.translated` 改为 `null`。

## Diagnose

日志文件分类：

- `DEBUG`: 包含一些请求的参数，具体的运行阶段等信息。
- `INFO`: 一些稍重要的运行阶段信息，主要用于进度报告，（e.g. 正在爬取某书）
- `WARNING`: 有可能造成书籍内容缺失的错误，需要重视
- `CRITICAL`: 严重错误，某些组件无法运行，某些任务无法完成。
- `ERROR`: 记录每个 `Exception` 的详细信息 （`traceback` 等）
