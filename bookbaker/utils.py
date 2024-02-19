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
