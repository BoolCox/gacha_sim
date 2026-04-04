from pathlib import Path
import base64

from nonebot.adapters.onebot.v11 import MessageEvent, MessageSegment
from nonebot_plugin_alconna import on_alconna
from nonebot_plugin_htmlkit import md_to_pic

menu = on_alconna("菜单")


@menu.handle()
async def _(event: MessageEvent):
    path = Path() / "README.md"
    pic = await md_to_pic(md_path=str(path))
    pic_b64 = base64.b64encode(pic).decode("ascii")
    await menu.finish(
        MessageSegment.reply(event.message_id) +
        MessageSegment.image(f"base64://{pic_b64}")
    )
