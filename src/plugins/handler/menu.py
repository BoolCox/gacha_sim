import base64
from pathlib import Path

from nonebot.adapters.onebot.v11 import MessageEvent, MessageSegment
from nonebot_plugin_alconna import on_alconna
from nonebot_plugin_htmlkit import md_to_pic

from ..dependencies.permission import ADMIN_PERMISSION

PROJECT_ROOT = Path(__file__).resolve().parents[3]
USER_MENU_PATH = PROJECT_ROOT / "docs" / "README.user.md"
ADMIN_MENU_PATH = PROJECT_ROOT / "docs" / "README.admin.md"

menu = on_alconna("菜单")
admin_menu = on_alconna("管理员菜单", permission=ADMIN_PERMISSION)


async def _send_menu_pic(event: MessageEvent, md_path: Path, matcher):
    pic = await md_to_pic(md_path=str(md_path))
    pic_b64 = base64.b64encode(pic).decode("ascii")
    await matcher.finish(
        MessageSegment.reply(event.message_id)
        + MessageSegment.image(f"base64://{pic_b64}")
    )


@menu.handle()
async def _(event: MessageEvent):
    await _send_menu_pic(event, USER_MENU_PATH, menu)


@admin_menu.handle()
async def _(event: MessageEvent):
    await _send_menu_pic(event, ADMIN_MENU_PATH, admin_menu)
