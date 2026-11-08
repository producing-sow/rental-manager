from __future__ import annotations

import argparse
import json
import mimetypes
import re
import threading
import time
import webbrowser
from datetime import date
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, quote, unquote, urlparse

from rental_core import (
    ApiError,
    DEFAULT_DB_PATH,
    add_months,
    add_payment,
    combined_pdf_bytes,
    confirm_bill,
    connection,
    create_bill_draft,
    create_property,
    create_room,
    dashboard_data,
    delete_cost,
    delete_payment,
    export_backup,
    get_bill_json,
    get_settings,
    init_db,
    ledger_csv_bytes,
    ledger_data,
    list_bills,
    list_properties,
    month_shift,
    next_pending_room,
    pdf_bytes_for_bill,
    property_detail,
    restore_backup,
    room_detail,
    seed_demo,
    set_bill_payment_status,
    set_settings,
    today_str,
    update_bill_draft,
    update_property,
    update_room,
    upsert_cost,
    void_bill,
    zip_pdfs,
)


BASE_DIR = Path(__file__).resolve().parent
WEB_DIR = BASE_DIR / "web"
MAX_BODY = 80 * 1024 * 1024


def _to_int(value: Any, name: str = "编号") -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        raise ApiError(f"{name}不正确")


def _ids_from_query(query: dict[str, list[str]]) -> list[int]:
    raw = (query.get("ids") or [""])[0]
    values = [item.strip() for item in raw.split(",") if item.strip()]
    if not values:
        raise ApiError("请选择要导出的收据")
    try:
        return [int(item) for item in values]
    except ValueError:
        raise ApiError("收据编号不正确")


def _calendar_months(conn, selected: str | None = None) -> list[str]:
    months = {
        date.today().strftime("%Y-%m"),
        selected or date.today().strftime("%Y-%m"),
    }
    for row in conn.execute("SELECT DISTINCT ledger_month FROM bills"):
        months.add(row["ledger_month"])
    for row in conn.execute("SELECT DISTINCT ledger_month FROM costs"):
        months.add(row["ledger_month"])
    current = date.today().replace(day=1)
    for offset in range(1, 7):
        months.add(add_months(current, -offset).strftime("%Y-%m"))
    return sorted(months, reverse=True)


def _default_month(conn) -> str:
    current = date.today().strftime("%Y-%m")
    available = [
        row["ledger_month"]
        for row in conn.execute(
            "SELECT DISTINCT ledger_month FROM bills WHERE status = 'confirmed' "
            "UNION SELECT DISTINCT ledger_month FROM costs"
        )
    ]
    if current in available:
        return current
    if available:
        return max(available)
    return current


def _bootstrap(conn) -> dict[str, Any]:
    month = _default_month(conn)
    return {
        "today": today_str(),
        "current_month": date.today().strftime("%Y-%m"),
        "default_month": month,
        "months": _calendar_months(conn, month),
        "settings": get_settings(conn),
    }


class AppHandler(BaseHTTPRequestHandler):
    server_version = "RentalManager/1.0"
    db_path: Path = DEFAULT_DB_PATH

    def log_message(self, fmt: str, *args: Any) -> None:
        return

    def _send_json(self, payload: Any, status: int = 200) -> None:
        body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(body)

    def _send_bytes(
        self,
        payload: bytes,
        content_type: str,
        *,
        filename: str | None = None,
        inline: bool = False,
        status: int = 200,
    ) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        if filename:
            disposition = "inline" if inline else "attachment"
            encoded = quote(filename)
            self.send_header(
                "Content-Disposition",
                f"{disposition}; filename=\"download\"; filename*=UTF-8''{encoded}",
            )
        self.end_headers()
        self.wfile.write(payload)

    def _read_json(self) -> dict[str, Any]:
        try:
            length = int(self.headers.get("Content-Length", "0") or 0)
        except ValueError:
            raise ApiError("请求长度不正确")
        if length > MAX_BODY:
            raise ApiError("请求内容过大", 413)
        raw = self.rfile.read(length) if length else b"{}"
        try:
            payload = json.loads(raw.decode("utf-8") or "{}")
        except (UnicodeDecodeError, json.JSONDecodeError):
            raise ApiError("请求数据不是有效 JSON")
        if not isinstance(payload, dict):
            raise ApiError("请求数据格式不正确")
        return payload

    def _read_body(self) -> bytes:
        try:
            length = int(self.headers.get("Content-Length", "0") or 0)
        except ValueError:
            raise ApiError("请求长度不正确")
        if length > MAX_BODY:
            raise ApiError("文件过大", 413)
        return self.rfile.read(length)

    def do_GET(self) -> None:
        try:
            parsed = urlparse(self.path)
            if parsed.path.startswith("/api/"):
                self._handle_api_get(parsed.path, parse_qs(parsed.query))
            else:
                self._serve_static(parsed.path)
        except ApiError as exc:
            self._send_json({"error": exc.message}, exc.status)
        except BrokenPipeError:
            return
        except Exception as exc:
            self._send_json({"error": f"服务器内部错误：{exc}"}, 500)

    def do_POST(self) -> None:
        try:
            parsed = urlparse(self.path)
            if parsed.path == "/api/settings/restore":
                body = self._read_body()
                if not body:
                    raise ApiError("请选择备份文件")
                restore_backup(self.db_path, body)
                with connection(self.db_path) as conn:
                    self._send_json({"ok": True, "settings": get_settings(conn)})
                return
            if not parsed.path.startswith("/api/"):
                raise ApiError("接口不存在", 404)
            self._handle_api_post(parsed.path, parse_qs(parsed.query), self._read_json())
        except ApiError as exc:
            self._send_json({"error": exc.message}, exc.status)
        except BrokenPipeError:
            return
        except Exception as exc:
            self._send_json({"error": f"服务器内部错误：{exc}"}, 500)

    def do_PUT(self) -> None:
        try:
            parsed = urlparse(self.path)
            if not parsed.path.startswith("/api/"):
                raise ApiError("接口不存在", 404)
            self._handle_api_put(parsed.path, parse_qs(parsed.query), self._read_json())
        except ApiError as exc:
            self._send_json({"error": exc.message}, exc.status)
        except BrokenPipeError:
            return
        except Exception as exc:
            self._send_json({"error": f"服务器内部错误：{exc}"}, 500)

    def do_DELETE(self) -> None:
        try:
            parsed = urlparse(self.path)
            if not parsed.path.startswith("/api/"):
                raise ApiError("接口不存在", 404)
            self._handle_api_delete(parsed.path, parse_qs(parsed.query))
        except ApiError as exc:
            self._send_json({"error": exc.message}, exc.status)
        except BrokenPipeError:
            return
        except Exception as exc:
            self._send_json({"error": f"服务器内部错误：{exc}"}, 500)

    def _serve_static(self, request_path: str) -> None:
        if request_path in ("", "/"):
            file_path = WEB_DIR / "index.html"
        else:
            relative = unquote(request_path).lstrip("/")
            file_path = (WEB_DIR / relative).resolve()
            try:
                file_path.relative_to(WEB_DIR.resolve())
            except ValueError:
                raise ApiError("文件不存在", 404)
        if not file_path.is_file():
            if "." not in request_path.rsplit("/", 1)[-1]:
                file_path = WEB_DIR / "index.html"
            else:
                raise ApiError("文件不存在", 404)
        content_type = mimetypes.guess_type(str(file_path))[0] or "application/octet-stream"
        if file_path.suffix == ".js":
            content_type = "text/javascript; charset=utf-8"
        elif file_path.suffix == ".css":
            content_type = "text/css; charset=utf-8"
        elif file_path.suffix == ".html":
            content_type = "text/html; charset=utf-8"
        elif file_path.suffix == ".svg":
            content_type = "image/svg+xml"
        data = file_path.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-cache")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(data)

    def _handle_api_get(self, path: str, query: dict[str, list[str]]) -> None:
        with connection(self.db_path) as conn:
            if path == "/api/health":
                self._send_json({"ok": True, "today": today_str()})
                return
            if path == "/api/bootstrap":
                self._send_json(_bootstrap(conn))
                return
            month = (query.get("month") or [_default_month(conn)])[0]
            if path == "/api/dashboard":
                self._send_json(dashboard_data(conn, month))
                return
            if path == "/api/ledger":
                self._send_json(ledger_data(conn, month))
                return
            if path == "/api/settings":
                self._send_json(get_settings(conn))
                return
            if path == "/api/settings/backup":
                payload = export_backup(conn)
                date_label = date.today().strftime("%Y%m%d")
                self._send_bytes(
                    payload,
                    "application/zip",
                    filename=f"出租房收租备份_{date_label}.zip",
                )
                return
            if path == "/api/properties":
                self._send_json({"properties": list_properties(conn, month), "month": month})
                return
            match = re.fullmatch(r"/api/properties/(\d+)", path)
            if match:
                self._send_json(property_detail(conn, int(match.group(1)), month))
                return
            match = re.fullmatch(r"/api/properties/(\d+)/next-room", path)
            if match:
                after_room_id = (query.get("after_room_id") or [""])[0]
                self._send_json(
                    {
                        "next_room": next_pending_room(
                            conn,
                            int(match.group(1)),
                            month,
                            int(after_room_id) if after_room_id else None,
                        )
                    }
                )
                return
            match = re.fullmatch(r"/api/rooms/(\d+)", path)
            if match:
                self._send_json(room_detail(conn, int(match.group(1))))
                return
            if path == "/api/bills":
                property_id = query.get("property_id", [None])[0]
                room_id = query.get("room_id", [None])[0]
                status = query.get("status", [None])[0]
                payment_status = query.get("payment_status", [None])[0]
                self._send_json(
                    {
                        "bills": list_bills(
                            conn,
                            month=month if month else None,
                            property_id=int(property_id) if property_id else None,
                            room_id=int(room_id) if room_id else None,
                            status=status or None,
                            payment_status=payment_status or None,
                        ),
                        "month": month,
                    }
                )
                return
            match = re.fullmatch(r"/api/bills/(\d+)", path)
            if match:
                self._send_json(get_bill_json(conn, int(match.group(1))))
                return
            match = re.fullmatch(r"/api/bills/(\d+)/pdf", path)
            if match:
                payload, filename = pdf_bytes_for_bill(conn, int(match.group(1)))
                self._send_bytes(payload, "application/pdf", filename=filename, inline=True)
                return
            if path == "/api/export/bills.pdf":
                bill_ids = _ids_from_query(query)
                payload, filename = combined_pdf_bytes(conn, bill_ids)
                self._send_bytes(payload, "application/pdf", filename=filename)
                return
            if path == "/api/export/bills.zip":
                bill_ids = _ids_from_query(query)
                payload, filename = zip_pdfs(conn, bill_ids)
                self._send_bytes(payload, "application/zip", filename=filename)
                return
            if path == "/api/export/ledger.csv":
                payload, filename = ledger_csv_bytes(conn, month)
                self._send_bytes(payload, "text/csv; charset=utf-8", filename=filename)
                return
        raise ApiError("接口不存在", 404)

    def _handle_api_post(
        self, path: str, query: dict[str, list[str]], payload: dict[str, Any]
    ) -> None:
        with connection(self.db_path) as conn:
            if path == "/api/properties":
                self._send_json(create_property(conn, payload), 201)
                return
            if path == "/api/rooms":
                self._send_json(create_room(conn, payload), 201)
                return
            match = re.fullmatch(r"/api/rooms/(\d+)/bills/new", path)
            if match:
                bill_id, reused = create_bill_draft(conn, int(match.group(1)), payload)
                self._send_json({"bill": get_bill_json(conn, bill_id), "reused": reused})
                return
            match = re.fullmatch(r"/api/bills/(\d+)/confirm", path)
            if match:
                self._send_json(
                    confirm_bill(
                        conn,
                        int(match.group(1)),
                        str(payload.get("payment_status") or "paid"),
                    )
                )
                return
            match = re.fullmatch(r"/api/bills/(\d+)/payment-status", path)
            if match:
                self._send_json(
                    set_bill_payment_status(
                        conn,
                        int(match.group(1)),
                        str(payload.get("status") or ""),
                    )
                )
                return
            match = re.fullmatch(r"/api/bills/(\d+)/void", path)
            if match:
                self._send_json(void_bill(conn, int(match.group(1)), str(payload.get("reason") or "")))
                return
            match = re.fullmatch(r"/api/bills/(\d+)/payments", path)
            if match:
                self._send_json(add_payment(conn, int(match.group(1)), payload), 201)
                return
            if path == "/api/costs":
                self._send_json(upsert_cost(conn, payload), 201)
                return
            if path == "/api/demo/seed":
                seed_demo(conn)
                self._send_json({"ok": True, "message": "示例数据已载入"})
                return
        raise ApiError("接口不存在", 404)

    def _handle_api_put(
        self, path: str, query: dict[str, list[str]], payload: dict[str, Any]
    ) -> None:
        with connection(self.db_path) as conn:
            if path == "/api/settings":
                self._send_json(set_settings(conn, payload))
                return
            match = re.fullmatch(r"/api/properties/(\d+)", path)
            if match:
                self._send_json(update_property(conn, int(match.group(1)), payload))
                return
            match = re.fullmatch(r"/api/rooms/(\d+)", path)
            if match:
                self._send_json(update_room(conn, int(match.group(1)), payload))
                return
            match = re.fullmatch(r"/api/bills/(\d+)", path)
            if match:
                self._send_json(update_bill_draft(conn, int(match.group(1)), payload))
                return
        raise ApiError("接口不存在", 404)

    def _handle_api_delete(self, path: str, query: dict[str, list[str]]) -> None:
        with connection(self.db_path) as conn:
            match = re.fullmatch(r"/api/payments/(\d+)", path)
            if match:
                delete_payment(conn, int(match.group(1)))
                self._send_json({"ok": True})
                return
            match = re.fullmatch(r"/api/costs/(\d+)", path)
            if match:
                delete_cost(conn, int(match.group(1)))
                self._send_json({"ok": True})
                return
        raise ApiError("接口不存在", 404)


def run_server(db_path: Path, port: int, open_browser: bool = True) -> None:
    init_db(db_path)
    AppHandler.db_path = db_path.resolve()
    server = ThreadingHTTPServer(("127.0.0.1", port), AppHandler)
    server.daemon_threads = True
    if open_browser:
        threading.Timer(0.8, lambda: webbrowser.open(f"http://127.0.0.1:{port}/")).start()
    print(f"出租房收租管理系统已启动：http://127.0.0.1:{port}/")
    print("关闭此窗口即可停止软件。")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


def main() -> None:
    parser = argparse.ArgumentParser(description="出租房收租管理系统")
    parser.add_argument("--port", type=int, default=8848, help="本机访问端口")
    parser.add_argument("--db", type=str, default=str(DEFAULT_DB_PATH), help="数据库文件")
    parser.add_argument("--no-browser", action="store_true", help="启动时不打开浏览器")
    args = parser.parse_args()
    run_server(Path(args.db), args.port, not args.no_browser)


if __name__ == "__main__":
    main()
