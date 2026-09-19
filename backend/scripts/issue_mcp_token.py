#!/usr/bin/env python3
"""Lấy `session_token` của MuMuAINovel để dùng làm `MUMU_MCP_TOKEN` cho MCP client.

Vì sao cần script này?
    Backend xác thực bằng cookie `session_token` (HMAC-signed) do middleware đọc.
    Backend KHÔNG hỗ trợ header `Authorization: Bearer ...`, nên MCP client phải nhận
    đúng giá trị cookie này qua biến môi trường `MUMU_MCP_TOKEN`.

Ví dụ:
    python backend/scripts/issue_mcp_token.py --username admin
    python backend/scripts/issue_mcp_token.py --username admin --password <pw> --quiet
    python backend/scripts/issue_mcp_token.py --email me@example.com --code 123456
    python backend/scripts/issue_mcp_token.py --check --token <token>

Lưu ý an toàn:
    Token = toàn bộ quyền của user đó. Script chỉ in ra stdout, KHÔNG ghi ra đĩa.
    Không commit token, không dán token vào issue hay file cấu hình mẫu.

Không cần cài thêm thư viện: chỉ dùng thư viện chuẩn của Python.
"""

from __future__ import annotations

import argparse
import getpass
import http.cookiejar
import json
import os
import sys
import time
import urllib.error
import urllib.request


DEFAULT_BASE_URL = "http://127.0.0.1:8000"
SESSION_COOKIE_NAME = "session_token"
EXPIRY_COOKIE_NAME = "session_expire_at"
HTTP_TIMEOUT_SECONDS = 30.0


class ApiError(Exception):
    """Lỗi khi gọi API. `status=None` nghĩa là không kết nối được (backend chưa chạy)."""

    def __init__(self, message: str, status: int | None = None) -> None:
        super().__init__(message)
        self.status = status


def _force_utf8_output() -> None:
    """Console Windows mặc định là cp1252 và sẽ crash khi in tiếng Việt có dấu."""
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            try:
                reconfigure(encoding="utf-8", errors="replace")
            except (ValueError, OSError):
                pass


def _post_json(base_url: str, path: str, payload: dict, jar: http.cookiejar.CookieJar) -> dict:
    """Gửi POST JSON, dùng cookie jar để bắt Set-Cookie."""
    body = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        f"{base_url}{path}",
        data=body,
        headers={"Content-Type": "application/json", "Accept": "application/json"},
        method="POST",
    )
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))
    return _send(opener, request)


def _get_json(base_url: str, path: str, token: str) -> dict:
    """Gửi GET kèm cookie session_token (không có Authorization header)."""
    request = urllib.request.Request(
        f"{base_url}{path}",
        headers={"Accept": "application/json", "Cookie": f"{SESSION_COOKIE_NAME}={token}"},
        method="GET",
    )
    return _send(urllib.request.build_opener(), request)


def _send(opener: urllib.request.OpenerDirector, request: urllib.request.Request) -> dict:
    try:
        with opener.open(request, timeout=HTTP_TIMEOUT_SECONDS) as response:
            raw = response.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        try:
            detail = json.loads(detail).get("detail", detail)
        except (ValueError, AttributeError):
            pass
        raise ApiError(f"HTTP {exc.code} từ {request.full_url} — {detail}", status=exc.code) from exc
    except urllib.error.URLError as exc:
        raise ApiError(
            f"không kết nối được {request.full_url} ({exc.reason}). "
            "Backend đã chạy chưa? MUMU_API_BASE có đúng không?"
        ) from exc

    if not raw.strip():
        return {}
    try:
        return json.loads(raw)
    except ValueError:
        return {"_raw": raw}


def _find_cookie(jar: http.cookiejar.CookieJar, name: str) -> str | None:
    for cookie in jar:
        if cookie.name == name:
            return cookie.value
    return None


def _describe_expiry(expiry_raw: str | None) -> str:
    if not expiry_raw:
        return "không rõ (xem SESSION_EXPIRE_MINUTES)"
    try:
        expiry_epoch = int(expiry_raw)
    except ValueError:
        return "không rõ"
    remaining_minutes = int((expiry_epoch - time.time()) / 60)
    stamp = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(expiry_epoch))
    if remaining_minutes <= 0:
        return f"{stamp} (đã hết hạn)"
    return f"{stamp} (còn ~{remaining_minutes} phút)"


def _obtain_token(args: argparse.Namespace) -> tuple[str, str | None, dict]:
    base_url = args.base_url.rstrip("/")
    jar = http.cookiejar.CookieJar()

    if args.email:
        if not args.code:
            raise SystemExit("LỖI: cần --code (mã xác minh đã gửi tới email) khi dùng --email.")
        response = _post_json(base_url, "/api/auth/email/login", {"email": args.email, "code": args.code}, jar)
    else:
        username = args.username or os.environ.get("LOCAL_AUTH_USERNAME") or "admin"
        password = args.password
        if not password:
            password = getpass.getpass(f"Mật khẩu cho '{username}': ")
        response = _post_json(
            base_url, "/api/auth/local/login", {"username": username, "password": password}, jar
        )

    token = _find_cookie(jar, SESSION_COOKIE_NAME)
    if not token:
        raise SystemExit(
            "LỖI: login không trả cookie session_token. "
            "Kiểm tra LOCAL_AUTH_ENABLED trong .env và thông tin đăng nhập."
        )
    return token, _find_cookie(jar, EXPIRY_COOKIE_NAME), response


def _user_id_from_response(response: dict) -> str | None:
    """Login response bọc user trong `user`; đôi khi chỉ có `user_id` ở cấp cao nhất."""
    user = response.get("user")
    if isinstance(user, dict):
        candidate = user.get("user_id")
        if isinstance(candidate, str) and candidate:
            return candidate
    candidate = response.get("user_id")
    return candidate if isinstance(candidate, str) and candidate else None


def main(argv: list[str] | None = None) -> int:
    _force_utf8_output()

    parser = argparse.ArgumentParser(
        description="Lấy session_token của MuMuAINovel để đặt vào MUMU_MCP_TOKEN của MCP client.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--base-url", default=os.environ.get("MUMU_API_BASE") or DEFAULT_BASE_URL,
                        help=f"Gốc REST API (mặc định: {DEFAULT_BASE_URL})")
    parser.add_argument("--username", help="Tên đăng nhập local (mặc định: LOCAL_AUTH_USERNAME hoặc 'admin')")
    parser.add_argument("--password", help="Mật khẩu local; bỏ trống sẽ được hỏi ẩn")
    parser.add_argument("--email", help="Đăng nhập bằng email (cần kèm --code)")
    parser.add_argument("--code", help="Mã xác minh email (dùng cùng --email)")
    parser.add_argument("--check", action="store_true", help="Chỉ kiểm tra token trong --token còn sống hay không")
    parser.add_argument("--token", help="Token cần kiểm tra khi dùng --check")
    parser.add_argument("--quiet", action="store_true", help="Chỉ in đúng token, tiện cho pipe/script")
    args = parser.parse_args(argv)

    base_url = args.base_url.rstrip("/")

    if args.check:
        token = args.token or os.environ.get("MUMU_MCP_TOKEN")
        if not token:
            raise SystemExit("LỖI: cần --token hoặc biến môi trường MUMU_MCP_TOKEN để kiểm tra.")
        try:
            user = _get_json(base_url, "/api/auth/user", token)
        except ApiError as exc:
            if exc.status is None:
                print(f"LỖI: {exc}", file=sys.stderr)
                return 2
            if exc.status == 401:
                print(f"Token KHÔNG hợp lệ hoặc đã hết hạn. ({exc})", file=sys.stderr)
                return 1
            print(f"LỖI: {exc}", file=sys.stderr)
            return 1
        print(f"OK: token còn hiệu lực (user: {user.get('username') or user.get('user_id') or '?'})")
        return 0

    try:
        token, expiry_raw, response = _obtain_token(args)
    except ApiError as exc:
        print(f"LỖI: {exc}", file=sys.stderr)
        return 2 if exc.status is None else 1

    if args.quiet:
        print(token)
        return 0

    print("Đăng nhập thành công." if response.get("success", True) else "Cảnh báo: response báo không thành công.")
    print()
    print("MUMU_MCP_TOKEN (dán vào cấu hình MCP, KHÔNG commit):")
    print(token)
    print()
    print(f"Hết hạn: {_describe_expiry(expiry_raw)}")

    user_id = _user_id_from_response(response)
    if user_id:
        print()
        print("Session token đã mang sẵn user id, nên MUMU_MCP_USER_ID là TUỲ CHỌN")
        print("khi dùng session token. Chỉ cần đặt khi bạn dùng shared token (Cách B):")
        print(f"MUMU_MCP_USER_ID={user_id}")

    print("Kiểm tra lại: python backend/scripts/issue_mcp_token.py --check --token <token>")
    return 0


if __name__ == "__main__":
    sys.exit(main())
