import re
import bs4
from base64 import b64decode
from vermils.io import aio
from .classes import Context


async def get_url_content(url: str, origin: str, ctx: Context) -> bytes:
    if url.startswith("http"):
        r = await ctx.client.get(
            url,
            headers={"Origin": origin},
            follow_redirects=True,
        )
        r.raise_for_status()
        data = r.content
    elif url.startswith("base64://"):
        data = b64decode(url.removeprefix("base64://"))
    elif url.startswith("file://"):
        async with aio.open(url.removeprefix("file://"), "rb") as f:
            data = await f.read()
    else:
        raise ValueError(f"Cannot download URL: {url}")
    return data

_ruby_re = re.compile(r"<ruby>.*?<\/ruby>")
_un_ruby_re = re.compile(r"\s?\[.*?\]\(\^.*?\)\s?")


def escape_ruby(s: str) -> str:
    ruby_matches = _ruby_re.findall(s)
    for match in ruby_matches:
        base = ''
        top = ''
        soup = bs4.BeautifulSoup(match, "xml")
        for child in soup.ruby.children:
            if isinstance(child, bs4.NavigableString):
                base += child.strip('\n')
            elif child.name == "rb":
                base += child.text.strip('\n')
            elif child.name == "rt":
                top += child.text.strip('\n')
        replacement = f" [{base}](^{top}) "
        s = s.replace(match, replacement)
    return s


def unescape_ruby(s: str) -> str:
    ruby_matches = _un_ruby_re.findall(s)
    for match in ruby_matches:
        base: str
        top: str
        base, top = match.strip(' ')[1:-1].split("](^")
        base, top = base.strip(' '), top.strip(' ')
        replacement = f"<ruby><rb>{base}</rb><rt>{top}</rt></ruby>"
        s = s.replace(match, replacement)
    return s
