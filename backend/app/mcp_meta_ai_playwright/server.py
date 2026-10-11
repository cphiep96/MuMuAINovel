"""stdio MCP: meta.ai video qua Playwright profile (login tay)."""
from __future__ import annotations

import argparse
from typing import Any, Optional

from mcp.server.fastmcp import FastMCP

from app.mcp_meta_ai_playwright.browser import (
    check_session,
    create_video,
    default_profile_dir,
    open_login_browser,
)

server = FastMCP(
    "MetaAI-Playwright",
    instructions=(
        "POC: tạo video trên https://www.meta.ai/create bằng Chromium profile đăng nhập tay. "
        "Chạy meta_ai_login trước, sau đó meta_ai_create_video."
    ),
)


@server.tool(
    name="meta_ai_login",
    description="Mở trình duyệt (profile lưu tại backend/data/meta_ai_playwright_profile). Đăng nhập Meta/Facebook tay trên meta.ai/create.",
)
async def meta_ai_login(wait_minutes: int = 15) -> dict[str, Any]:
    return await open_login_browser(wait_minutes=max(1, min(wait_minutes, 60)))


@server.tool(
    name="meta_ai_check_session",
    description="Kiểm tra profile Playwright còn đăng nhập meta.ai không (headless).",
)
async def meta_ai_check_session() -> dict[str, Any]:
    return await check_session()


@server.tool(
    name="meta_ai_create_video",
    description=(
        "Upload ảnh tham chiếu + prompt trên meta.ai/create, chờ video, tải MP4 về storage/meta_ai_videos."
    ),
)
async def meta_ai_create_video(
    prompt: str,
    image_path: str,
    output_path: Optional[str] = None,
    timeout_sec: int = 600,
) -> dict[str, Any]:
    try:
        return await create_video(
            prompt=prompt,
            image_path=image_path,
            output_path=output_path,
            timeout_sec=max(120, min(int(timeout_sec), 1800)),
        )
    except Exception as exc:  # noqa: BLE001 — MCP tool phải trả lỗi có cấu trúc
        return {
            "success": False,
            "message": str(exc) or type(exc).__name__,
            "profile_dir": str(default_profile_dir()),
            "prompt": prompt,
            "image_path": image_path,
        }


def main() -> None:
    parser = argparse.ArgumentParser(description="Meta AI Playwright MCP / CLI")
    parser.add_argument(
        "command",
        nargs="?",
        default="mcp",
        choices=("mcp", "login", "check", "create"),
        help="mcp=stdio MCP server; login/check/create=CLI thử nhanh",
    )
    parser.add_argument("--prompt", default="")
    parser.add_argument("--image", default="")
    parser.add_argument("--output", default="")
    parser.add_argument("--timeout", type=int, default=600)
    parser.add_argument("--wait-minutes", type=int, default=15)
    args = parser.parse_args()

    if args.command == "mcp":
        server.run(transport="stdio")
        return

    import asyncio

    if args.command == "login":
        result = asyncio.run(open_login_browser(wait_minutes=args.wait_minutes))
    elif args.command == "check":
        result = asyncio.run(check_session())
    else:
        if not args.prompt or not args.image:
            raise SystemExit("create cần --prompt và --image")
        try:
            result = asyncio.run(
                create_video(
                    prompt=args.prompt,
                    image_path=args.image,
                    output_path=args.output or None,
                    timeout_sec=args.timeout,
                )
            )
        except Exception as exc:  # noqa: BLE001
            result = {"success": False, "message": str(exc) or type(exc).__name__}
    print(result)


if __name__ == "__main__":
    main()
