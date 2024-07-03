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
_un_ruby_re = re.compile(r"((?<!\\)[【\[](.*?)[】\]]\(\^(.*?)(?<!\\)\))")
_rep_re = re.compile(r"((.)\2{8,})")
_un_rep_re = re.compile(r"((?<!\\)[【\[](.*?)[】\]]\(\*(\d+)(?<!\\)\))")


def escape_keychars(s: str) -> str:
    return (
        s.replace('[', r"\[")
        # s.replace('[', r"\]")  # This is not needed
        .replace('(', r"\(")
        .replace(')', r"\)")
    )


def unescape_keychars(s: str) -> str:
    return (
        s.replace(r"\[", '[')
        # .replace(r"\]", ']')  # This is not needed
        .replace(r"\(", '(')
        .replace(r"\)", ')')
    )


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
        base = escape_keychars(base)
        top = escape_keychars(top)
        replacement = f"[{base}](^{top})"
        s = s.replace(match, replacement)
    return s


def unescape_ruby(s: str) -> str:
    ruby_matches = _un_ruby_re.findall(s)
    for match in ruby_matches:
        base: str
        top: str
        full, base, top = match
        base = unescape_keychars(base)
        top = unescape_keychars(top)
        replacement = f"<ruby><rb>{base}</rb><rt>{top}</rt></ruby>"
        s = s.replace(full, replacement)
    return s


def escape_repetition(s: str) -> str:
    reps = _rep_re.findall(s)
    for match in reps:
        full, pattern = match
        rep_n = len(full) // len(pattern)
        pattern = escape_keychars(pattern)
        replacement = f"[{pattern}](*{rep_n})"
        s = s.replace(full, replacement)
    return s


def unescape_repetition(s: str) -> str:
    matches = _un_rep_re.findall(s)
    for match in matches:
        full, pattern, rep_n = match
        rep_n = int(rep_n)
        pattern = unescape_keychars(pattern)
        replacement = pattern * rep_n
        s = s.replace(full, replacement)
    return s
