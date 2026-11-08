from __future__ import annotations

import calendar
import csv
import io
import json
import os
import re
import shutil
import sqlite3
import tempfile
import zipfile
from contextlib import contextmanager
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from pathlib import Path
from typing import Any, Iterator

from receipt_pdf import build_combined_receipts_pdf, build_receipt_pdf, rmb_upper, suggested_pdf_name


BASE_DIR = Path(__file__).resolve().parent
DEFAULT_DB_PATH = BASE_DIR / "data" / "rental.db"

SETTING_DEFAULTS = {
    "receipt_title": "租金收据",
    "receipt_prefix": "",
    "next_receipt_no": "1",
    "issuer_name": "房东",
    "payee_name": "房东",
    "show_tenant_on_receipt": "0",
    "receipt_note": "请及时缴纳本期费用，谢谢配合。",
    "overdue_days": "7",
}

SCHEMA = """
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS properties (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    address TEXT NOT NULL DEFAULT '',
    note TEXT NOT NULL DEFAULT '',
    sort_order INTEGER NOT NULL DEFAULT 0,
    archived INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS rooms (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    property_id INTEGER NOT NULL REFERENCES properties(id),
    room_no TEXT NOT NULL,
    tenant_name TEXT NOT NULL DEFAULT '',
    phone TEXT NOT NULL DEFAULT '',
    rent_cents INTEGER NOT NULL DEFAULT 0,
    electric_rate_cents INTEGER NOT NULL DEFAULT 100,
    water_rate_cents INTEGER NOT NULL DEFAULT 500,
    billing_day INTEGER NOT NULL DEFAULT 19,
    electric_auto_enabled INTEGER NOT NULL DEFAULT 0,
    electric_auto_increment_x100 INTEGER NOT NULL DEFAULT 0,
    water_auto_enabled INTEGER NOT NULL DEFAULT 0,
    water_auto_increment_x100 INTEGER NOT NULL DEFAULT 0,
    status TEXT NOT NULL DEFAULT 'rented',
    note TEXT NOT NULL DEFAULT '',
    sort_order INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(property_id, room_no)
);

CREATE TABLE IF NOT EXISTS bills (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    receipt_no TEXT UNIQUE,
    room_id INTEGER NOT NULL REFERENCES rooms(id),
    property_id INTEGER NOT NULL REFERENCES properties(id),
    property_name TEXT NOT NULL,
    room_no TEXT NOT NULL,
    tenant_name TEXT NOT NULL DEFAULT '',
    start_date TEXT NOT NULL,
    end_date TEXT NOT NULL,
    issue_date TEXT NOT NULL,
    ledger_month TEXT NOT NULL,
    rent_cents INTEGER NOT NULL DEFAULT 0,
    prev_electric_x100 INTEGER,
    current_electric_x100 INTEGER,
    electric_auto_locked INTEGER NOT NULL DEFAULT 0,
    electric_rate_cents INTEGER NOT NULL DEFAULT 100,
    prev_water_x100 INTEGER,
    current_water_x100 INTEGER,
    water_auto_locked INTEGER NOT NULL DEFAULT 0,
    water_rate_cents INTEGER NOT NULL DEFAULT 500,
    electric_cents INTEGER NOT NULL DEFAULT 0,
    water_cents INTEGER NOT NULL DEFAULT 0,
    other1_name TEXT NOT NULL DEFAULT '',
    other1_cents INTEGER NOT NULL DEFAULT 0,
    other2_name TEXT NOT NULL DEFAULT '',
    other2_cents INTEGER NOT NULL DEFAULT 0,
    other3_name TEXT NOT NULL DEFAULT '',
    other3_cents INTEGER NOT NULL DEFAULT 0,
    total_cents INTEGER NOT NULL DEFAULT 0,
    status TEXT NOT NULL DEFAULT 'draft',
    note TEXT NOT NULL DEFAULT '',
    void_reason TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    confirmed_at TEXT
);

CREATE TABLE IF NOT EXISTS payments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    bill_id INTEGER NOT NULL REFERENCES bills(id) ON DELETE CASCADE,
    amount_cents INTEGER NOT NULL,
    paid_at TEXT NOT NULL,
    method TEXT NOT NULL DEFAULT '微信',
    note TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS costs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    property_id INTEGER NOT NULL REFERENCES properties(id),
    ledger_month TEXT NOT NULL,
    cost_type TEXT NOT NULL,
    name TEXT NOT NULL DEFAULT '',
    amount_cents INTEGER NOT NULL DEFAULT 0,
    note TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS activity_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    action TEXT NOT NULL,
    entity_type TEXT NOT NULL,
    entity_id INTEGER,
    detail TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_costs_utility_unique
ON costs(property_id, ledger_month, cost_type)
WHERE cost_type IN ('water', 'electricity');

CREATE INDEX IF NOT EXISTS idx_bills_room_period
ON bills(room_id, start_date, end_date);

CREATE INDEX IF NOT EXISTS idx_bills_ledger_status
ON bills(ledger_month, status);

CREATE INDEX IF NOT EXISTS idx_bills_property
ON bills(property_id, ledger_month, status);

CREATE UNIQUE INDEX IF NOT EXISTS idx_bills_room_period_unique
ON bills(room_id, start_date, end_date)
WHERE status <> 'void';

CREATE INDEX IF NOT EXISTS idx_payments_bill
ON payments(bill_id);

CREATE INDEX IF NOT EXISTS idx_costs_property_month
ON costs(property_id, ledger_month);
"""


class ApiError(Exception):
    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.message = message
        self.status = status


def now_iso() -> str:
    return datetime.now().replace(microsecond=0).isoformat()


def today_str() -> str:
    return date.today().isoformat()


def connect(db_path: Path | str = DEFAULT_DB_PATH) -> sqlite3.Connection:
    conn = sqlite3.connect(str(db_path), timeout=15)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    return conn


@contextmanager
def connection(db_path: Path | str = DEFAULT_DB_PATH) -> Iterator[sqlite3.Connection]:
    conn = connect(db_path)
    try:
        yield conn
    finally:
        conn.close()


def _ensure_column(
    conn: sqlite3.Connection,
    table: str,
    column: str,
    definition: str,
) -> None:
    columns = {
        row["name"]
        for row in conn.execute(f"PRAGMA table_info({table})")
    }
    if column not in columns:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")


def init_db(db_path: Path | str = DEFAULT_DB_PATH) -> None:
    path = Path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with connection(path) as conn:
        conn.executescript(SCHEMA)
        _ensure_column(conn, "rooms", "electric_auto_enabled", "INTEGER NOT NULL DEFAULT 0")
        _ensure_column(
            conn,
            "rooms",
            "electric_auto_increment_x100",
            "INTEGER NOT NULL DEFAULT 0",
        )
        _ensure_column(conn, "rooms", "water_auto_enabled", "INTEGER NOT NULL DEFAULT 0")
        _ensure_column(
            conn,
            "rooms",
            "water_auto_increment_x100",
            "INTEGER NOT NULL DEFAULT 0",
        )
        _ensure_column(
            conn,
            "bills",
            "electric_auto_locked",
            "INTEGER NOT NULL DEFAULT 0",
        )
        _ensure_column(conn, "bills", "water_auto_locked", "INTEGER NOT NULL DEFAULT 0")
        timestamp = now_iso()
        for key, value in SETTING_DEFAULTS.items():
            conn.execute(
                "INSERT OR IGNORE INTO settings(key, value) VALUES (?, ?)",
                (key, value),
            )
        conn.commit()


def get_settings(conn: sqlite3.Connection) -> dict[str, str]:
    values = dict(SETTING_DEFAULTS)
    for row in conn.execute("SELECT key, value FROM settings"):
        values[row["key"]] = row["value"]
    return values


def set_settings(conn: sqlite3.Connection, values: dict[str, Any]) -> dict[str, str]:
    allowed = set(SETTING_DEFAULTS)
    for key, value in values.items():
        if key in allowed:
            conn.execute(
                "INSERT INTO settings(key, value) VALUES (?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                (key, str(value)),
            )
    conn.commit()
    return get_settings(conn)


def log_activity(
    conn: sqlite3.Connection,
    action: str,
    entity_type: str,
    entity_id: int | None,
    detail: str = "",
) -> None:
    conn.execute(
        "INSERT INTO activity_log(action, entity_type, entity_id, detail, created_at) "
        "VALUES (?, ?, ?, ?, ?)",
        (action, entity_type, entity_id, detail, now_iso()),
    )


def parse_date(value: str, field_name: str = "日期") -> date:
    try:
        return date.fromisoformat(str(value))
    except (TypeError, ValueError):
        raise ApiError(f"{field_name}格式不正确，应为 YYYY-MM-DD")


def parse_month(value: str, field_name: str = "经营账期") -> str:
    try:
        parsed = date.fromisoformat(f"{value}-01")
    except (TypeError, ValueError):
        raise ApiError(f"{field_name}格式不正确，应为 YYYY-MM")
    return parsed.strftime("%Y-%m")


def add_months(value: date, count: int) -> date:
    month_index = value.year * 12 + (value.month - 1) + count
    year = month_index // 12
    month = month_index % 12 + 1
    day = min(value.day, calendar.monthrange(year, month)[1])
    return date(year, month, day)


def month_shift(month: str, count: int) -> str:
    parsed = date.fromisoformat(f"{month}-01")
    return add_months(parsed, count).strftime("%Y-%m")


def suggested_period(today: date | None = None, billing_day: int = 19) -> tuple[date, date]:
    current = today or date.today()
    day = max(1, min(28, int(billing_day or 19)))
    year, month = current.year, current.month
    if current.day >= day:
        start = date(year, month, min(day, calendar.monthrange(year, month)[1]))
    else:
        previous = add_months(date(year, month, 1), -1)
        start = date(
            previous.year,
            previous.month,
            min(day, calendar.monthrange(previous.year, previous.month)[1]),
        )
    end = add_months(start, 1) - timedelta(days=1)
    return start, end


def period_for_ledger_month(month: str, billing_day: int = 19) -> tuple[date, date]:
    ledger = parse_month(month)
    parsed = date.fromisoformat(f"{ledger}-01")
    day = max(1, min(28, int(billing_day or 19)))
    previous = add_months(parsed, -1)
    start = date(
        previous.year,
        previous.month,
        min(day, calendar.monthrange(previous.year, previous.month)[1]),
    )
    end = add_months(start, 1) - timedelta(days=1)
    return start, end


def parse_number(value: Any, field_name: str) -> Decimal:
    if value is None or value == "":
        raise ApiError(f"{field_name}不能为空")
    try:
        number = Decimal(str(value))
    except (InvalidOperation, ValueError):
        raise ApiError(f"{field_name}必须是数字")
    if not number.is_finite():
        raise ApiError(f"{field_name}必须是有效数字")
    return number


def money_to_cents(
    value: Any,
    field_name: str,
    *,
    allow_empty: bool = False,
    allow_negative: bool = False,
) -> int | None:
    if value is None or value == "":
        if allow_empty:
            return None
        raise ApiError(f"{field_name}不能为空")
    number = parse_number(value, field_name).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    if number < 0 and not allow_negative:
        raise ApiError(f"{field_name}不能为负数")
    return int(number * 100)


def reading_to_x100(value: Any, field_name: str, *, allow_empty: bool = False) -> int | None:
    if value is None or value == "":
        if allow_empty:
            return None
        raise ApiError(f"{field_name}不能为空")
    number = parse_number(value, field_name).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    if number < 0:
        raise ApiError(f"{field_name}不能为负数")
    return int(number * 100)


def _round_div(numerator: int, denominator: int) -> int:
    if numerator >= 0:
        return (numerator + denominator // 2) // denominator
    return -((-numerator + denominator // 2) // denominator)


def line_amount(
    previous_x100: int | None,
    current_x100: int | None,
    rate_cents: int,
) -> tuple[int | None, int]:
    if previous_x100 is None or current_x100 is None:
        return None, 0
    usage_x100 = int(current_x100) - int(previous_x100)
    amount_cents = _round_div(usage_x100 * int(rate_cents), 100)
    return usage_x100, amount_cents


def _x100_to_number(value: int | None) -> float | None:
    if value is None:
        return None
    return round(int(value) / 100, 2)


def _cents_to_number(value: int | None) -> float:
    return round(int(value or 0) / 100, 2)


def calculate_bill_values(values: dict[str, Any]) -> dict[str, int]:
    rent_cents = int(values.get("rent_cents") or 0)
    electric_rate_cents = int(values.get("electric_rate_cents") or 0)
    water_rate_cents = int(values.get("water_rate_cents") or 0)
    electric_usage, electric_cents = line_amount(
        values.get("prev_electric_x100"),
        values.get("current_electric_x100"),
        electric_rate_cents,
    )
    water_usage, water_cents = line_amount(
        values.get("prev_water_x100"),
        values.get("current_water_x100"),
        water_rate_cents,
    )
    other_cents = sum(
        int(values.get(f"other{slot}_cents") or 0) for slot in (1, 2, 3)
    )
    total_cents = rent_cents + electric_cents + water_cents + other_cents
    return {
        "electric_usage_x100": electric_usage or 0,
        "water_usage_x100": water_usage or 0,
        "electric_cents": electric_cents,
        "water_cents": water_cents,
        "total_cents": total_cents,
    }


def _payments_for(conn: sqlite3.Connection, bill_id: int) -> list[sqlite3.Row]:
    return list(
        conn.execute(
            "SELECT * FROM payments WHERE bill_id = ? ORDER BY paid_at, id",
            (bill_id,),
        )
    )


def _payment_total(conn: sqlite3.Connection, bill_id: int) -> int:
    row = conn.execute(
        "SELECT COALESCE(SUM(amount_cents), 0) AS total FROM payments WHERE bill_id = ?",
        (bill_id,),
    ).fetchone()
    return int(row["total"] or 0)


def bill_to_json(conn: sqlite3.Connection, row: sqlite3.Row | dict[str, Any]) -> dict[str, Any]:
    data = dict(row)
    electric_usage, electric_cents = line_amount(
        data.get("prev_electric_x100"),
        data.get("current_electric_x100"),
        int(data.get("electric_rate_cents") or 0),
    )
    water_usage, water_cents = line_amount(
        data.get("prev_water_x100"),
        data.get("current_water_x100"),
        int(data.get("water_rate_cents") or 0),
    )
    payment_rows = _payments_for(conn, int(data["id"]))
    paid_cents = sum(int(item["amount_cents"]) for item in payment_rows)
    total_cents = int(data.get("total_cents") or 0)
    if data.get("status") == "void":
        payment_status = "void"
    elif data.get("status") == "confirmed" and total_cents <= 0:
        payment_status = "paid"
    elif paid_cents <= 0:
        payment_status = "unpaid"
    elif paid_cents >= total_cents:
        payment_status = "paid"
    else:
        payment_status = "partial"

    overdue_days = 7
    try:
        overdue_days = int(get_settings(conn).get("overdue_days", "7"))
    except ValueError:
        pass
    overdue = False
    if data.get("status") == "confirmed" and payment_status != "paid":
        try:
            overdue = date.today() > parse_date(data["end_date"]) + timedelta(days=overdue_days)
        except Exception:
            overdue = False

    other_fees = []
    for slot in (1, 2, 3):
        name = data.get(f"other{slot}_name") or ""
        amount = int(data.get(f"other{slot}_cents") or 0)
        if name or amount:
            other_fees.append(
                {
                    "slot": slot,
                    "name": name or f"其他费用{slot}",
                    "amount_cents": amount,
                    "amount": _cents_to_number(amount),
                }
            )

    return {
        "id": int(data["id"]),
        "receipt_no": data.get("receipt_no"),
        "room_id": int(data["room_id"]),
        "property_id": int(data["property_id"]),
        "property_name": data.get("property_name") or "",
        "room_no": data.get("room_no") or "",
        "tenant_name": data.get("tenant_name") or "",
        "start_date": data.get("start_date"),
        "end_date": data.get("end_date"),
        "issue_date": data.get("issue_date"),
        "ledger_month": data.get("ledger_month"),
        "rent_cents": int(data.get("rent_cents") or 0),
        "rent": _cents_to_number(data.get("rent_cents")),
        "prev_electric": _x100_to_number(data.get("prev_electric_x100")),
        "current_electric": _x100_to_number(data.get("current_electric_x100")),
        "electric_auto_locked": bool(data.get("electric_auto_locked")),
        "electric_usage": _x100_to_number(electric_usage),
        "electric_rate": _cents_to_number(data.get("electric_rate_cents")),
        "electric_cents": electric_cents,
        "electric": _cents_to_number(electric_cents),
        "prev_water": _x100_to_number(data.get("prev_water_x100")),
        "current_water": _x100_to_number(data.get("current_water_x100")),
        "water_auto_locked": bool(data.get("water_auto_locked")),
        "water_usage": _x100_to_number(water_usage),
        "water_rate": _cents_to_number(data.get("water_rate_cents")),
        "water_cents": water_cents,
        "water": _cents_to_number(water_cents),
        "other_fees": other_fees,
        "total_cents": total_cents,
        "total": _cents_to_number(total_cents),
        "chinese_total": rmb_upper(total_cents),
        "status": data.get("status"),
        "payment_status": payment_status,
        "paid_cents": paid_cents,
        "paid": _cents_to_number(paid_cents),
        "outstanding_cents": max(0, total_cents - paid_cents),
        "outstanding": _cents_to_number(max(0, total_cents - paid_cents)),
        "overdue": overdue,
        "note": data.get("note") or "",
        "void_reason": data.get("void_reason") or "",
        "created_at": data.get("created_at"),
        "updated_at": data.get("updated_at"),
        "confirmed_at": data.get("confirmed_at"),
        "payments": [
            {
                "id": int(item["id"]),
                "amount_cents": int(item["amount_cents"]),
                "amount": _cents_to_number(item["amount_cents"]),
                "paid_at": item["paid_at"],
                "method": item["method"],
                "note": item["note"],
            }
            for item in payment_rows
        ],
    }


def get_bill_row(conn: sqlite3.Connection, bill_id: int) -> sqlite3.Row:
    row = conn.execute("SELECT * FROM bills WHERE id = ?", (bill_id,)).fetchone()
    if not row:
        raise ApiError("收据不存在", 404)
    return row


def get_bill_json(conn: sqlite3.Connection, bill_id: int) -> dict[str, Any]:
    return bill_to_json(conn, get_bill_row(conn, bill_id))


def _natural_sort_key(value: Any) -> tuple:
    parts = re.split(r"(\d+)", str(value or ""))
    return tuple(
        (0, int(part)) if part.isdigit() else (1, part.casefold())
        for part in parts
        if part
    )


def ordered_bills_for_summary(
    conn: sqlite3.Connection,
    bill_ids: list[int],
) -> list[dict[str, Any]]:
    bills = [get_bill_json(conn, bill_id) for bill_id in dict.fromkeys(bill_ids)]
    properties = {
        int(row["id"]): row
        for row in conn.execute(
            "SELECT id, name, sort_order FROM properties"
        )
    }

    def sort_key(bill: dict[str, Any]) -> tuple:
        prop = properties.get(int(bill["property_id"]))
        if prop:
            property_key = (
                int(prop["sort_order"]),
                int(prop["id"]),
                _natural_sort_key(prop["name"]),
            )
        else:
            property_key = (
                10**9,
                int(bill["property_id"]),
                _natural_sort_key(bill["property_name"]),
            )
        return (
            property_key,
            _natural_sort_key(bill["room_no"]),
            str(bill.get("start_date") or ""),
            int(bill["id"]),
        )

    return sorted(bills, key=sort_key)


def latest_bill_row(
    conn: sqlite3.Connection,
    room_id: int,
    *,
    statuses: tuple[str, ...] = ("draft", "confirmed"),
) -> sqlite3.Row | None:
    placeholders = ",".join("?" for _ in statuses)
    return conn.execute(
        f"SELECT * FROM bills WHERE room_id = ? AND status IN ({placeholders}) "
        "ORDER BY start_date DESC, id DESC LIMIT 1",
        (room_id, *statuses),
    ).fetchone()


def _ensure_no_overlap(
    conn: sqlite3.Connection,
    room_id: int,
    start: date,
    end: date,
    exclude_bill_id: int | None = None,
) -> None:
    params: list[Any] = [room_id, end.isoformat(), start.isoformat()]
    clause = ""
    if exclude_bill_id is not None:
        clause = " AND id <> ?"
        params.append(exclude_bill_id)
    row = conn.execute(
        "SELECT id, receipt_no FROM bills "
        "WHERE room_id = ? AND status <> 'void' AND NOT(end_date < ? OR start_date > ?)"
        + clause
        + " LIMIT 1",
        params,
    ).fetchone()
    if row:
        raise ApiError(
            f"该房间在这个时间段已有收据{('：' + row['receipt_no']) if row['receipt_no'] else '草稿'}，不能重复创建",
            409,
        )


def get_room(conn: sqlite3.Connection, room_id: int) -> sqlite3.Row:
    row = conn.execute(
        "SELECT r.*, p.name AS property_name, p.address AS property_address "
        "FROM rooms r JOIN properties p ON p.id = r.property_id "
        "WHERE r.id = ? AND p.archived = 0",
        (room_id,),
    ).fetchone()
    if not row:
        raise ApiError("房间不存在", 404)
    return row


def get_property(conn: sqlite3.Connection, property_id: int) -> sqlite3.Row:
    row = conn.execute(
        "SELECT * FROM properties WHERE id = ? AND archived = 0",
        (property_id,),
    ).fetchone()
    if not row:
        raise ApiError("房源不存在", 404)
    return row


def create_bill_draft(
    conn: sqlite3.Connection,
    room_id: int,
    payload: dict[str, Any] | None = None,
) -> tuple[int, bool]:
    payload = payload or {}
    room = get_room(conn, room_id)
    latest = latest_bill_row(conn, room_id)
    if latest and latest["status"] == "draft":
        return int(latest["id"]), True

    custom = bool(payload.get("custom_dates"))
    if custom:
        start = parse_date(payload.get("start_date"), "账单周期开始日期")
        end = parse_date(payload.get("end_date"), "账单周期结束日期")
    elif latest and latest["status"] == "confirmed":
        start = add_months(parse_date(latest["start_date"]), 1)
        end = add_months(parse_date(latest["end_date"]), 1)
    else:
        start, end = suggested_period(billing_day=int(room["billing_day"] or 19))

    if end < start:
        raise ApiError("账单周期结束日期不能早于开始日期")

    existing = conn.execute(
        "SELECT * FROM bills WHERE room_id = ? AND start_date = ? AND end_date = ? "
        "AND status <> 'void' LIMIT 1",
        (room_id, start.isoformat(), end.isoformat()),
    ).fetchone()
    if existing:
        return int(existing["id"]), True

    _ensure_no_overlap(conn, room_id, start, end)

    previous = conn.execute(
        "SELECT * FROM bills WHERE room_id = ? AND status = 'confirmed' "
        "AND end_date < ? ORDER BY end_date DESC, id DESC LIMIT 1",
        (room_id, start.isoformat()),
    ).fetchone()

    if previous:
        prev_electric = previous["current_electric_x100"]
        prev_water = previous["current_water_x100"]
        rent_cents = int(previous["rent_cents"])
        electric_rate_cents = int(previous["electric_rate_cents"])
        water_rate_cents = int(previous["water_rate_cents"])
    else:
        prev_electric = None
        prev_water = None
        rent_cents = int(room["rent_cents"] or 0)
        electric_rate_cents = int(room["electric_rate_cents"] or 100)
        water_rate_cents = int(room["water_rate_cents"] or 500)

    electric_auto_locked = bool(
        previous
        and room["electric_auto_enabled"]
        and prev_electric is not None
    )
    water_auto_locked = bool(
        previous
        and room["water_auto_enabled"]
        and prev_water is not None
    )
    current_electric = (
        int(prev_electric) + int(room["electric_auto_increment_x100"] or 0)
        if electric_auto_locked
        else None
    )
    current_water = (
        int(prev_water) + int(room["water_auto_increment_x100"] or 0)
        if water_auto_locked
        else None
    )

    issue_date = parse_date(payload.get("issue_date") or today_str(), "收据日期")
    ledger_month = (
        parse_month(payload["ledger_month"])
        if payload.get("ledger_month")
        else end.strftime("%Y-%m")
    )
    timestamp = now_iso()
    values = {
        "rent_cents": rent_cents,
        "prev_electric_x100": prev_electric,
        "current_electric_x100": current_electric,
        "electric_auto_locked": electric_auto_locked,
        "electric_rate_cents": electric_rate_cents,
        "prev_water_x100": prev_water,
        "current_water_x100": current_water,
        "water_auto_locked": water_auto_locked,
        "water_rate_cents": water_rate_cents,
        "other1_cents": 0,
        "other2_cents": 0,
        "other3_cents": 0,
    }
    calculated = calculate_bill_values(values)
    cursor = conn.execute(
        """
        INSERT INTO bills(
            receipt_no, room_id, property_id, property_name, room_no, tenant_name,
            start_date, end_date, issue_date, ledger_month,
            rent_cents, prev_electric_x100, current_electric_x100, electric_auto_locked,
            electric_rate_cents, prev_water_x100, current_water_x100, water_auto_locked,
            water_rate_cents,
            electric_cents, water_cents, total_cents, status, created_at, updated_at
        ) VALUES (NULL, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, 0, ?, 'draft', ?, ?)
        """,
        (
            room_id,
            int(room["property_id"]),
            room["property_name"],
            room["room_no"],
            room["tenant_name"],
            start.isoformat(),
            end.isoformat(),
            issue_date.isoformat(),
            ledger_month,
            rent_cents,
            prev_electric,
            current_electric,
            int(electric_auto_locked),
            electric_rate_cents,
            prev_water,
            current_water,
            int(water_auto_locked),
            water_rate_cents,
            calculated["total_cents"],
            timestamp,
            timestamp,
        ),
    )
    bill_id = int(cursor.lastrowid)
    log_activity(conn, "create_draft", "bill", bill_id, f"{room['property_name']} {room['room_no']}")
    conn.commit()
    return bill_id, False


def update_bill_draft(conn: sqlite3.Connection, bill_id: int, payload: dict[str, Any]) -> dict[str, Any]:
    row = get_bill_row(conn, bill_id)
    if row["status"] != "draft":
        raise ApiError("已确认或已作废的收据不能直接修改，请先作废重开", 409)

    current = dict(row)
    if payload.get("start_date"):
        current["start_date"] = parse_date(payload["start_date"], "账单周期开始日期").isoformat()
    if payload.get("end_date"):
        current["end_date"] = parse_date(payload["end_date"], "账单周期结束日期").isoformat()
    start = parse_date(current["start_date"])
    end = parse_date(current["end_date"])
    if end < start:
        raise ApiError("账单周期结束日期不能早于开始日期")
    _ensure_no_overlap(conn, int(row["room_id"]), start, end, exclude_bill_id=bill_id)

    if "issue_date" in payload:
        current["issue_date"] = parse_date(payload["issue_date"], "收据日期").isoformat()
    if "ledger_month" in payload:
        current["ledger_month"] = parse_month(payload["ledger_month"])
    if "tenant_name" in payload:
        current["tenant_name"] = str(payload.get("tenant_name") or "").strip()
    if "note" in payload:
        current["note"] = str(payload.get("note") or "").strip()
    if "rent" in payload:
        current["rent_cents"] = money_to_cents(
            payload.get("rent"),
            "房租",
            allow_negative=True,
        )
    if "electric_rate" in payload:
        current["electric_rate_cents"] = money_to_cents(payload.get("electric_rate"), "电费单价")
    if "water_rate" in payload:
        current["water_rate_cents"] = money_to_cents(payload.get("water_rate"), "水费单价")
    if "prev_electric" in payload:
        current["prev_electric_x100"] = reading_to_x100(
            payload.get("prev_electric"), "上月电表读数", allow_empty=True
        )
    if "electric_auto_locked" in payload:
        current["electric_auto_locked"] = 1 if payload.get("electric_auto_locked") else 0
    if "current_electric" in payload:
        next_current_electric = reading_to_x100(
            payload.get("current_electric"), "本月电表读数", allow_empty=True
        )
        if (
            row["electric_auto_locked"]
            and current["electric_auto_locked"]
            and next_current_electric != current["current_electric_x100"]
        ):
            raise ApiError("本月电表由自动填写锁定，请先点击解锁")
        current["current_electric_x100"] = next_current_electric
    if "prev_water" in payload:
        current["prev_water_x100"] = reading_to_x100(
            payload.get("prev_water"), "上月水表读数", allow_empty=True
        )
    if "water_auto_locked" in payload:
        current["water_auto_locked"] = 1 if payload.get("water_auto_locked") else 0
    if "current_water" in payload:
        next_current_water = reading_to_x100(
            payload.get("current_water"), "本月水表读数", allow_empty=True
        )
        if (
            row["water_auto_locked"]
            and current["water_auto_locked"]
            and next_current_water != current["current_water_x100"]
        ):
            raise ApiError("本月水表由自动填写锁定，请先点击解锁")
        current["current_water_x100"] = next_current_water

    for slot in (1, 2, 3):
        name_key = f"other{slot}_name"
        amount_key = f"other{slot}"
        if name_key in payload:
            current[name_key] = str(payload.get(name_key) or "").strip()
        if amount_key in payload:
            amount = money_to_cents(payload.get(amount_key), f"其他费用{slot}", allow_empty=True)
            current[f"other{slot}_cents"] = amount or 0
            if amount and not current.get(name_key):
                current[name_key] = f"其他费用{slot}"

    calculated = calculate_bill_values(current)
    conn.execute(
        """
        UPDATE bills SET
            start_date = ?, end_date = ?, issue_date = ?, ledger_month = ?, tenant_name = ?,
            rent_cents = ?, prev_electric_x100 = ?, current_electric_x100 = ?,
            electric_auto_locked = ?, electric_rate_cents = ?, prev_water_x100 = ?,
            current_water_x100 = ?, water_auto_locked = ?,
            water_rate_cents = ?, electric_cents = ?, water_cents = ?,
            other1_name = ?, other1_cents = ?, other2_name = ?, other2_cents = ?,
            other3_name = ?, other3_cents = ?, total_cents = ?, note = ?, updated_at = ?
        WHERE id = ? AND status = 'draft'
        """,
        (
            current["start_date"],
            current["end_date"],
            current["issue_date"],
            current["ledger_month"],
            current.get("tenant_name", ""),
            int(current.get("rent_cents") or 0),
            current.get("prev_electric_x100"),
            current.get("current_electric_x100"),
            int(current.get("electric_auto_locked") or 0),
            int(current.get("electric_rate_cents") or 0),
            current.get("prev_water_x100"),
            current.get("current_water_x100"),
            int(current.get("water_auto_locked") or 0),
            int(current.get("water_rate_cents") or 0),
            calculated["electric_cents"],
            calculated["water_cents"],
            current.get("other1_name", ""),
            int(current.get("other1_cents") or 0),
            current.get("other2_name", ""),
            int(current.get("other2_cents") or 0),
            current.get("other3_name", ""),
            int(current.get("other3_cents") or 0),
            calculated["total_cents"],
            current.get("note", ""),
            now_iso(),
            bill_id,
        ),
    )
    conn.commit()
    return get_bill_json(conn, bill_id)


def _next_receipt_no(conn: sqlite3.Connection) -> str:
    settings = get_settings(conn)
    try:
        sequence = max(1, int(settings.get("next_receipt_no", "1")))
    except ValueError:
        sequence = 1
    prefix = settings.get("receipt_prefix", "")
    while True:
        candidate = f"{prefix}{sequence:06d}"
        exists = conn.execute(
            "SELECT 1 FROM bills WHERE receipt_no = ? LIMIT 1", (candidate,)
        ).fetchone()
        if not exists:
            conn.execute(
                "INSERT INTO settings(key, value) VALUES ('next_receipt_no', ?) "
                "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                (str(sequence + 1),),
            )
            return candidate
        sequence += 1


def next_pending_room(
    conn: sqlite3.Connection,
    property_id: int,
    ledger_month: str,
    after_room_id: int | None = None,
) -> dict[str, Any] | None:
    """Return the next rented room that still needs a receipt for the month."""
    get_property(conn, property_id)
    rooms = list(
        conn.execute(
            "SELECT * FROM rooms WHERE property_id = ? AND status = 'rented' "
            "ORDER BY sort_order, id, room_no",
            (property_id,),
        )
    )
    if not rooms:
        return None

    pending: list[dict[str, Any]] = []
    for room in rooms:
        existing = conn.execute(
            "SELECT * FROM bills WHERE room_id = ? AND ledger_month = ? "
            "AND status IN ('draft', 'confirmed') "
            "ORDER BY start_date DESC, id DESC",
            (room["id"], ledger_month),
        ).fetchall()
        if any(row["status"] == "confirmed" for row in existing):
            continue
        draft = next((row for row in existing if row["status"] == "draft"), None)
        has_history = conn.execute(
            "SELECT 1 FROM bills WHERE room_id = ? AND status = 'confirmed' LIMIT 1",
            (room["id"],),
        ).fetchone()
        target_start, target_end = period_for_ledger_month(
            ledger_month,
            int(room["billing_day"] or 19),
        )
        pending.append(
            {
                "room_id": int(room["id"]),
                "room_no": room["room_no"],
                "tenant_name": room["tenant_name"],
                "action": "draft" if draft else "new",
                "bill_id": int(draft["id"]) if draft else None,
                "has_history": bool(has_history),
                "start_date": target_start.isoformat(),
                "end_date": target_end.isoformat(),
            }
        )

    if not pending:
        return None

    if after_room_id is None:
        return pending[0]
    room_ids = [int(room["id"]) for room in rooms]
    try:
        current_index = room_ids.index(int(after_room_id))
    except ValueError:
        return pending[0]
    ordered_ids = room_ids[current_index + 1 :] + room_ids[:current_index]
    pending_by_id = {item["room_id"]: item for item in pending}
    for room_id in ordered_ids:
        if room_id in pending_by_id:
            return pending_by_id[room_id]
    return pending[0]


def confirm_bill(
    conn: sqlite3.Connection,
    bill_id: int,
    payment_status: str = "paid",
) -> dict[str, Any]:
    if payment_status not in ("paid", "unpaid"):
        raise ApiError("收款状态不正确")
    conn.execute("BEGIN IMMEDIATE")
    try:
        row = get_bill_row(conn, bill_id)
        if row["status"] != "draft":
            raise ApiError("只有草稿收据可以确认", 409)
        if row["current_electric_x100"] is None:
            raise ApiError("请填写本月电表读数")
        if row["current_water_x100"] is None:
            raise ApiError("请填写本月水表读数")
        if row["prev_electric_x100"] is None:
            raise ApiError("请填写上月电表读数")
        if row["prev_water_x100"] is None:
            raise ApiError("请填写上月水表读数")
        if int(row["current_electric_x100"]) < int(row["prev_electric_x100"]):
            raise ApiError("本月电表读数不能小于上月电表读数")
        if int(row["current_water_x100"]) < int(row["prev_water_x100"]):
            raise ApiError("本月水表读数不能小于上月水表读数")
        _ensure_no_overlap(
            conn,
            int(row["room_id"]),
            parse_date(row["start_date"]),
            parse_date(row["end_date"]),
            exclude_bill_id=bill_id,
        )
        calculated = calculate_bill_values(dict(row))
        receipt_no = _next_receipt_no(conn)
        conn.execute(
            "UPDATE bills SET receipt_no = ?, status = 'confirmed', total_cents = ?, "
            "electric_cents = ?, water_cents = ?, confirmed_at = ?, updated_at = ? WHERE id = ?",
            (
                receipt_no,
                calculated["total_cents"],
                calculated["electric_cents"],
                calculated["water_cents"],
                now_iso(),
                now_iso(),
                bill_id,
            ),
        )
        if payment_status == "paid" and calculated["total_cents"] > 0:
            conn.execute(
                "INSERT INTO payments(bill_id, amount_cents, paid_at, method, note, created_at) "
                "VALUES (?, ?, ?, '默认已收', '确认收据时默认已收', ?)",
                (bill_id, calculated["total_cents"], row["issue_date"], now_iso()),
            )
        log_activity(conn, "confirm", "bill", bill_id, receipt_no)
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    result = get_bill_json(conn, bill_id)
    result["next_room"] = next_pending_room(
        conn,
        int(row["property_id"]),
        row["ledger_month"],
        after_room_id=int(row["room_id"]),
    )
    return result


def set_bill_payment_status(
    conn: sqlite3.Connection,
    bill_id: int,
    payment_status: str,
) -> dict[str, Any]:
    if payment_status not in ("paid", "unpaid"):
        raise ApiError("收款状态不正确")
    row = get_bill_row(conn, bill_id)
    if row["status"] != "confirmed":
        raise ApiError("只有已确认收据可以切换收款状态", 409)
    total_cents = int(row["total_cents"] or 0)
    payments = _payments_for(conn, bill_id)
    automatic_methods = ("默认已收", "历史导入", "调整已收")
    manual_payments = [
        item for item in payments if item["method"] not in automatic_methods
    ]

    if payment_status == "unpaid":
        if manual_payments:
            raise ApiError("这张收据已有手工收款记录，请先删除收款记录再设为未收", 409)
        conn.execute(
            "DELETE FROM payments WHERE bill_id = ? AND method IN ('默认已收', '历史导入', '调整已收')",
            (bill_id,),
        )
    elif total_cents > 0:
        paid_cents = sum(int(item["amount_cents"]) for item in payments)
        remaining = max(0, total_cents - paid_cents)
        if remaining:
            conn.execute(
                "INSERT INTO payments(bill_id, amount_cents, paid_at, method, note, created_at) "
                "VALUES (?, ?, ?, '默认已收', '点击已收时补齐收款', ?)",
                (bill_id, remaining, today_str(), now_iso()),
            )

    log_activity(conn, "payment_status", "bill", bill_id, payment_status)
    conn.commit()
    return get_bill_json(conn, bill_id)


def void_bill(conn: sqlite3.Connection, bill_id: int, reason: str) -> dict[str, Any]:
    row = get_bill_row(conn, bill_id)
    if row["status"] == "void":
        raise ApiError("该收据已经作废", 409)
    paid = _payment_total(conn, bill_id)
    if paid > 0:
        raise ApiError("该收据已有收款记录，请先删除收款记录再作废", 409)
    reason = (reason or "").strip()
    if not reason:
        raise ApiError("请填写作废原因")
    conn.execute(
        "UPDATE bills SET status = 'void', void_reason = ?, updated_at = ? WHERE id = ?",
        (reason, now_iso(), bill_id),
    )
    log_activity(conn, "void", "bill", bill_id, reason)
    conn.commit()
    return get_bill_json(conn, bill_id)


def add_payment(conn: sqlite3.Connection, bill_id: int, payload: dict[str, Any]) -> dict[str, Any]:
    bill = get_bill_row(conn, bill_id)
    if bill["status"] != "confirmed":
        raise ApiError("只有已确认收据可以登记收款", 409)
    amount_cents = money_to_cents(payload.get("amount"), "收款金额")
    if not amount_cents:
        raise ApiError("收款金额必须大于 0")
    paid_at = parse_date(payload.get("paid_at") or today_str(), "收款日期").isoformat()
    method = str(payload.get("method") or "微信").strip()
    note = str(payload.get("note") or "").strip()
    cursor = conn.execute(
        "INSERT INTO payments(bill_id, amount_cents, paid_at, method, note, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (bill_id, amount_cents, paid_at, method, note, now_iso()),
    )
    log_activity(conn, "payment", "bill", bill_id, f"{amount_cents / 100:.2f}")
    conn.commit()
    result = get_bill_json(conn, bill_id)
    result["new_payment_id"] = int(cursor.lastrowid)
    return result


def delete_payment(conn: sqlite3.Connection, payment_id: int) -> None:
    row = conn.execute("SELECT * FROM payments WHERE id = ?", (payment_id,)).fetchone()
    if not row:
        raise ApiError("收款记录不存在", 404)
    conn.execute("DELETE FROM payments WHERE id = ?", (payment_id,))
    log_activity(conn, "delete_payment", "bill", int(row["bill_id"]), str(row["amount_cents"]))
    conn.commit()


def list_properties(conn: sqlite3.Connection, month: str) -> list[dict[str, Any]]:
    props = list(
        conn.execute(
            "SELECT * FROM properties WHERE archived = 0 ORDER BY sort_order, id"
        )
    )
    result: list[dict[str, Any]] = []
    for prop in props:
        rooms = conn.execute(
            "SELECT * FROM rooms WHERE property_id = ? AND status <> 'inactive'",
            (prop["id"],),
        ).fetchall()
        billed = conn.execute(
            "SELECT COUNT(*) AS count, COALESCE(SUM(total_cents), 0) AS total "
            "FROM bills WHERE property_id = ? AND ledger_month = ? AND status = 'confirmed'",
            (prop["id"], month),
        ).fetchone()
        paid = conn.execute(
            "SELECT COALESCE(SUM(p.amount_cents), 0) AS total "
            "FROM payments p JOIN bills b ON b.id = p.bill_id "
            "WHERE b.property_id = ? AND b.ledger_month = ? AND b.status = 'confirmed'",
            (prop["id"], month),
        ).fetchone()
        result.append(
            {
                "id": int(prop["id"]),
                "name": prop["name"],
                "address": prop["address"],
                "note": prop["note"],
                "room_count": len(rooms),
                "rented_count": sum(1 for r in rooms if r["status"] == "rented"),
                "billed_count": int(billed["count"] or 0),
                "billed_cents": int(billed["total"] or 0),
                "received_cents": int(paid["total"] or 0),
            }
        )
    return result


def property_detail(conn: sqlite3.Connection, property_id: int, month: str) -> dict[str, Any]:
    prop = get_property(conn, property_id)
    rooms = list(
        conn.execute(
            "SELECT * FROM rooms WHERE property_id = ? ORDER BY status = 'inactive', sort_order, room_no",
            (property_id,),
        )
    )
    room_payloads: list[dict[str, Any]] = []
    for room in rooms:
        latest = latest_bill_row(conn, int(room["id"]))
        latest_json = bill_to_json(conn, latest) if latest else None
        current_month_bill = conn.execute(
            "SELECT * FROM bills WHERE room_id = ? AND ledger_month = ? AND status <> 'void' "
            "ORDER BY start_date DESC LIMIT 1",
            (room["id"], month),
        ).fetchone()
        room_payloads.append(
            {
                "id": int(room["id"]),
                "property_id": int(room["property_id"]),
                "room_no": room["room_no"],
                "tenant_name": room["tenant_name"],
                "phone": room["phone"],
                "rent_cents": int(room["rent_cents"]),
                "electric_rate_cents": int(room["electric_rate_cents"]),
                "water_rate_cents": int(room["water_rate_cents"]),
                "billing_day": int(room["billing_day"]),
                "electric_auto_enabled": bool(room["electric_auto_enabled"]),
                "electric_auto_increment_x100": int(room["electric_auto_increment_x100"]),
                "water_auto_enabled": bool(room["water_auto_enabled"]),
                "water_auto_increment_x100": int(room["water_auto_increment_x100"]),
                "status": room["status"],
                "note": room["note"],
                "latest_bill": latest_json,
                "month_bill": bill_to_json(conn, current_month_bill) if current_month_bill else None,
            }
        )
    return {
        "property": {
            "id": int(prop["id"]),
            "name": prop["name"],
            "address": prop["address"],
            "note": prop["note"],
        },
        "rooms": room_payloads,
    }


def room_detail(conn: sqlite3.Connection, room_id: int) -> dict[str, Any]:
    room = get_room(conn, room_id)
    bills = list(
        conn.execute(
            "SELECT * FROM bills WHERE room_id = ? ORDER BY start_date DESC, id DESC LIMIT 24",
            (room_id,),
        )
    )
    latest = bills[0] if bills else None
    suggested_start, suggested_end = suggested_period(
        billing_day=int(room["billing_day"] or 19)
    )
    next_start = (
        add_months(parse_date(latest["start_date"]), 1).isoformat() if latest else None
    )
    next_end = add_months(parse_date(latest["end_date"]), 1).isoformat() if latest else None
    return {
        "room": {
            "id": int(room["id"]),
            "property_id": int(room["property_id"]),
            "property_name": room["property_name"],
            "property_address": room["property_address"],
            "room_no": room["room_no"],
            "tenant_name": room["tenant_name"],
            "phone": room["phone"],
            "rent_cents": int(room["rent_cents"]),
            "electric_rate_cents": int(room["electric_rate_cents"]),
            "water_rate_cents": int(room["water_rate_cents"]),
            "billing_day": int(room["billing_day"]),
            "electric_auto_enabled": bool(room["electric_auto_enabled"]),
            "electric_auto_increment_x100": int(room["electric_auto_increment_x100"]),
            "water_auto_enabled": bool(room["water_auto_enabled"]),
            "water_auto_increment_x100": int(room["water_auto_increment_x100"]),
            "status": room["status"],
            "note": room["note"],
        },
        "bills": [bill_to_json(conn, row) for row in bills],
        "latest_bill": bill_to_json(conn, latest) if latest else None,
        "suggested_start": suggested_start.isoformat(),
        "suggested_end": suggested_end.isoformat(),
        "next_start": next_start,
        "next_end": next_end,
    }


def create_property(conn: sqlite3.Connection, payload: dict[str, Any]) -> dict[str, Any]:
    name = str(payload.get("name") or "").strip()
    if not name:
        raise ApiError("请填写房源名称")
    timestamp = now_iso()
    try:
        cursor = conn.execute(
            "INSERT INTO properties(name, address, note, sort_order, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (
                name,
                str(payload.get("address") or "").strip(),
                str(payload.get("note") or "").strip(),
                int(payload.get("sort_order") or 0),
                timestamp,
                timestamp,
            ),
        )
    except sqlite3.IntegrityError:
        raise ApiError("已经存在同名房源")
    conn.commit()
    return dict(get_property(conn, int(cursor.lastrowid)))


def update_property(
    conn: sqlite3.Connection, property_id: int, payload: dict[str, Any]
) -> dict[str, Any]:
    prop = get_property(conn, property_id)
    name = str(payload.get("name", prop["name"]) or "").strip()
    if not name:
        raise ApiError("请填写房源名称")
    try:
        conn.execute(
            "UPDATE properties SET name = ?, address = ?, note = ?, sort_order = ?, updated_at = ? "
            "WHERE id = ?",
            (
                name,
                str(payload.get("address", prop["address"]) or "").strip(),
                str(payload.get("note", prop["note"]) or "").strip(),
                int(payload.get("sort_order", prop["sort_order"]) or 0),
                now_iso(),
                property_id,
            ),
        )
    except sqlite3.IntegrityError:
        raise ApiError("已经存在同名房源")
    conn.commit()
    return dict(get_property(conn, property_id))


def _room_values(payload: dict[str, Any], existing: sqlite3.Row | None = None) -> tuple:
    def enabled_flag(key: str) -> int:
        value = payload.get(key, existing[key] if existing else 0)
        return 1 if value in (True, 1, "1", "true", "on") else 0

    room_no = str(payload.get("room_no", existing["room_no"] if existing else "") or "").strip()
    if not room_no:
        raise ApiError("请填写房间号")
    rent_cents = (
        money_to_cents(payload.get("rent"), "默认房租")
        if "rent" in payload
        else int(existing["rent_cents"] if existing else 0)
    )
    electric_rate = (
        money_to_cents(payload.get("electric_rate"), "电费单价")
        if "electric_rate" in payload
        else int(existing["electric_rate_cents"] if existing else 100)
    )
    water_rate = (
        money_to_cents(payload.get("water_rate"), "水费单价")
        if "water_rate" in payload
        else int(existing["water_rate_cents"] if existing else 500)
    )
    billing_day = int(payload.get("billing_day", existing["billing_day"] if existing else 19) or 19)
    if not 1 <= billing_day <= 28:
        raise ApiError("抄表日建议填写 1 至 28 日")
    electric_auto_enabled = enabled_flag("electric_auto_enabled")
    water_auto_enabled = enabled_flag("water_auto_enabled")
    electric_auto_increment = reading_to_x100(
        payload.get(
            "electric_auto_increment",
            _x100_to_number(existing["electric_auto_increment_x100"])
            if existing
            else 0,
        ),
        "电表每月自动增加量",
        allow_empty=True,
    ) or 0
    water_auto_increment = reading_to_x100(
        payload.get(
            "water_auto_increment",
            _x100_to_number(existing["water_auto_increment_x100"])
            if existing
            else 0,
        ),
        "水表每月自动增加量",
        allow_empty=True,
    ) or 0
    status = str(payload.get("status", existing["status"] if existing else "rented") or "rented")
    if status not in ("rented", "vacant", "inactive"):
        raise ApiError("房间状态不正确")
    return (
        room_no,
        str(payload.get("tenant_name", existing["tenant_name"] if existing else "") or "").strip(),
        str(payload.get("phone", existing["phone"] if existing else "") or "").strip(),
        rent_cents,
        electric_rate,
        water_rate,
        billing_day,
        electric_auto_enabled,
        electric_auto_increment,
        water_auto_enabled,
        water_auto_increment,
        status,
        str(payload.get("note", existing["note"] if existing else "") or "").strip(),
    )


def create_room(conn: sqlite3.Connection, payload: dict[str, Any]) -> dict[str, Any]:
    property_id = int(payload.get("property_id") or 0)
    get_property(conn, property_id)
    values = _room_values(payload)
    timestamp = now_iso()
    try:
        cursor = conn.execute(
            """
            INSERT INTO rooms(
                property_id, room_no, tenant_name, phone, rent_cents,
                electric_rate_cents, water_rate_cents, billing_day,
                electric_auto_enabled, electric_auto_increment_x100,
                water_auto_enabled, water_auto_increment_x100, status, note,
                sort_order, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                property_id,
                *values,
                int(payload.get("sort_order") or 0),
                timestamp,
                timestamp,
            ),
        )
    except sqlite3.IntegrityError:
        raise ApiError("该房源下已经有这个房间号")
    conn.commit()
    return dict(get_room(conn, int(cursor.lastrowid)))


def update_room(conn: sqlite3.Connection, room_id: int, payload: dict[str, Any]) -> dict[str, Any]:
    existing = get_room(conn, room_id)
    values = _room_values(payload, existing)
    try:
        conn.execute(
            """
            UPDATE rooms SET room_no = ?, tenant_name = ?, phone = ?, rent_cents = ?,
                electric_rate_cents = ?, water_rate_cents = ?, billing_day = ?,
                electric_auto_enabled = ?, electric_auto_increment_x100 = ?,
                water_auto_enabled = ?, water_auto_increment_x100 = ?,
                status = ?, note = ?, sort_order = ?, updated_at = ?
            WHERE id = ?
            """,
            (
                *values,
                int(payload.get("sort_order", existing["sort_order"]) or 0),
                now_iso(),
                room_id,
            ),
        )
    except sqlite3.IntegrityError:
        raise ApiError("该房源下已经有这个房间号")
    conn.commit()
    return dict(get_room(conn, room_id))


def list_bills(
    conn: sqlite3.Connection,
    *,
    month: str | None = None,
    property_id: int | None = None,
    room_id: int | None = None,
    status: str | None = None,
    payment_status: str | None = None,
) -> list[dict[str, Any]]:
    clauses: list[str] = []
    params: list[Any] = []
    if month:
        clauses.append("ledger_month = ?")
        params.append(month)
    if property_id:
        clauses.append("property_id = ?")
        params.append(property_id)
    if room_id:
        clauses.append("room_id = ?")
        params.append(room_id)
    if status:
        clauses.append("status = ?")
        params.append(status)
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    rows = conn.execute(
        f"SELECT * FROM bills {where} ORDER BY start_date DESC, id DESC", params
    ).fetchall()
    result = [bill_to_json(conn, row) for row in rows]
    if payment_status:
        result = [item for item in result if item["payment_status"] == payment_status]
    return result


def _summary_for_month(conn: sqlite3.Connection, month: str) -> dict[str, Any]:
    bills = [
        bill_to_json(conn, row)
        for row in conn.execute(
            "SELECT * FROM bills WHERE ledger_month = ? AND status = 'confirmed'",
            (month,),
        )
    ]
    billed = sum(item["total_cents"] for item in bills)
    paid = sum(item["paid_cents"] for item in bills)
    cost = int(
        conn.execute(
            "SELECT COALESCE(SUM(amount_cents), 0) AS total FROM costs WHERE ledger_month = ?",
            (month,),
        ).fetchone()["total"]
        or 0
    )
    return {
        "month": month,
        "billed_cents": billed,
        "received_cents": paid,
        "outstanding_cents": max(0, billed - paid),
        "cost_cents": cost,
        "profit_cents": billed - cost,
        "bill_count": len(bills),
        "unpaid_count": sum(1 for bill in bills if bill["payment_status"] != "paid"),
    }


def _property_ledger_rows(conn: sqlite3.Connection, month: str) -> list[dict[str, Any]]:
    props = list(
        conn.execute(
            "SELECT * FROM properties WHERE archived = 0 ORDER BY sort_order, id"
        )
    )
    rows: list[dict[str, Any]] = []
    for prop in props:
        bills = [
            bill_to_json(conn, row)
            for row in conn.execute(
                "SELECT * FROM bills WHERE property_id = ? AND ledger_month = ? "
                "AND status = 'confirmed'",
                (prop["id"], month),
            )
        ]
        rent = sum(item["rent_cents"] for item in bills)
        electric = sum(item["electric_cents"] for item in bills)
        water = sum(item["water_cents"] for item in bills)
        other = sum(
            sum(fee["amount_cents"] for fee in item["other_fees"]) for item in bills
        )
        billed = rent + electric + water + other
        received = sum(item["paid_cents"] for item in bills)
        costs = list(
            conn.execute(
                "SELECT * FROM costs WHERE property_id = ? AND ledger_month = ? "
                "ORDER BY cost_type, id",
                (prop["id"], month),
            )
        )
        water_cost = sum(int(c["amount_cents"]) for c in costs if c["cost_type"] == "water")
        electric_cost = sum(
            int(c["amount_cents"]) for c in costs if c["cost_type"] == "electricity"
        )
        other_cost = sum(int(c["amount_cents"]) for c in costs if c["cost_type"] == "other")
        total_cost = water_cost + electric_cost + other_cost
        profit = billed - total_cost
        rooms = conn.execute(
            "SELECT COUNT(*) AS count FROM rooms WHERE property_id = ? AND status <> 'inactive'",
            (prop["id"],),
        ).fetchone()
        rented = conn.execute(
            "SELECT COUNT(*) AS count FROM rooms WHERE property_id = ? AND status = 'rented'",
            (prop["id"],),
        ).fetchone()
        rows.append(
            {
                "id": int(prop["id"]),
                "name": prop["name"],
                "property_id": int(prop["id"]),
                "property_name": prop["name"],
                "address": prop["address"],
                "room_count": int(rooms["count"] or 0),
                "rented_count": int(rented["count"] or 0),
                "billed_count": len(bills),
                "rent_cents": rent,
                "electric_income_cents": electric,
                "water_income_cents": water,
                "other_income_cents": other,
                "billed_cents": billed,
                "received_cents": received,
                "outstanding_cents": max(0, billed - received),
                "electric_cost_cents": electric_cost,
                "water_cost_cents": water_cost,
                "other_cost_cents": other_cost,
                "cost_cents": total_cost,
                "utility_spread_cents": electric + water - electric_cost - water_cost,
                "profit_cents": profit,
                "margin": (profit / billed) if billed else None,
                "profit_status": "profit" if profit > 0 else "loss" if profit < 0 else "even",
                "cost_missing": (
                    not any(c["cost_type"] == "electricity" for c in costs)
                    or not any(c["cost_type"] == "water" for c in costs)
                ),
                "costs": [
                    {
                        "id": int(c["id"]),
                        "cost_type": c["cost_type"],
                        "name": c["name"],
                        "amount_cents": int(c["amount_cents"]),
                        "note": c["note"],
                    }
                    for c in costs
                ],
            }
        )
    return rows


def dashboard_data(conn: sqlite3.Connection, month: str) -> dict[str, Any]:
    current = _summary_for_month(conn, month)
    previous_month = month_shift(month, -1)
    previous = _summary_for_month(conn, previous_month)
    properties = _property_ledger_rows(conn, month)
    rooms = conn.execute(
        "SELECT COUNT(*) AS total, "
        "SUM(CASE WHEN status = 'rented' THEN 1 ELSE 0 END) AS rented "
        "FROM rooms r JOIN properties p ON p.id = r.property_id "
        "WHERE p.archived = 0 AND r.status <> 'inactive'"
    ).fetchone()
    recent_rows = conn.execute(
        "SELECT * FROM bills WHERE status = 'confirmed' ORDER BY confirmed_at DESC, id DESC LIMIT 8"
    ).fetchall()
    recent = [bill_to_json(conn, row) for row in recent_rows]
    for item in properties:
        prev_row = next(
            (row for row in _property_ledger_rows(conn, previous_month) if row["property_id"] == item["property_id"]),
            None,
        )
        item["previous_profit_cents"] = int(prev_row["profit_cents"]) if prev_row else 0
        item["previous_billed_cents"] = int(prev_row["billed_cents"]) if prev_row else 0
    current.update(
        {
            "previous": previous,
            "profit_delta_cents": current["profit_cents"] - previous["profit_cents"],
            "billed_delta_cents": current["billed_cents"] - previous["billed_cents"],
            "rooms_total": int(rooms["total"] or 0),
            "rooms_rented": int(rooms["rented"] or 0),
            "properties": properties,
            "recent_bills": recent,
            "draft_count": int(
                conn.execute(
                    "SELECT COUNT(*) AS count FROM bills WHERE status = 'draft'"
                ).fetchone()["count"]
                or 0
            ),
        }
    )
    return current


def _compare_value(current: int, previous: int) -> tuple[int, float | None]:
    delta = current - previous
    if previous == 0:
        return delta, None
    return delta, delta / abs(previous)


def ledger_data(conn: sqlite3.Connection, month: str) -> dict[str, Any]:
    previous_month = month_shift(month, -1)
    rows = _property_ledger_rows(conn, month)
    previous_rows = _property_ledger_rows(conn, previous_month)
    previous_by_id = {int(row["property_id"]): row for row in previous_rows}
    for row in rows:
        previous = previous_by_id.get(int(row["property_id"]))
        for field in (
            "billed_cents",
            "cost_cents",
            "profit_cents",
            "received_cents",
            "outstanding_cents",
            "electric_income_cents",
            "water_income_cents",
            "electric_cost_cents",
            "water_cost_cents",
            "utility_spread_cents",
        ):
            old = int(previous[field]) if previous else 0
            delta, rate = _compare_value(int(row[field]), old)
            row[f"previous_{field}"] = old
            row[f"delta_{field}"] = delta
            row[f"rate_{field}"] = rate
        row["previous_margin"] = previous.get("margin") if previous else None

    summary = _summary_for_month(conn, month)
    previous_summary = _summary_for_month(conn, previous_month)
    summary["profit_delta_cents"] = summary["profit_cents"] - previous_summary["profit_cents"]
    summary["billed_delta_cents"] = summary["billed_cents"] - previous_summary["billed_cents"]
    summary["cost_delta_cents"] = summary["cost_cents"] - previous_summary["cost_cents"]

    rooms_rows = conn.execute(
        "SELECT r.*, p.name AS property_name FROM rooms r "
        "JOIN properties p ON p.id = r.property_id "
        "WHERE p.archived = 0 AND r.status <> 'inactive' "
        "ORDER BY p.sort_order, p.id, r.sort_order, r.room_no"
    ).fetchall()
    room_rows: list[dict[str, Any]] = []
    for room in rooms_rows:
        current_row = conn.execute(
            "SELECT * FROM bills WHERE room_id = ? AND ledger_month = ? "
            "AND status = 'confirmed' ORDER BY start_date DESC, id DESC LIMIT 1",
            (room["id"], month),
        ).fetchone()
        previous_row = None
        if current_row:
            previous_row = conn.execute(
                "SELECT * FROM bills WHERE room_id = ? AND status = 'confirmed' "
                "AND start_date < ? ORDER BY start_date DESC, id DESC LIMIT 1",
                (room["id"], current_row["start_date"]),
            ).fetchone()
        else:
            previous_row = conn.execute(
                "SELECT * FROM bills WHERE room_id = ? AND status = 'confirmed' "
                "AND ledger_month < ? ORDER BY start_date DESC, id DESC LIMIT 1",
                (room["id"], month),
            ).fetchone()
        current_bill = bill_to_json(conn, current_row) if current_row else None
        previous_bill = bill_to_json(conn, previous_row) if previous_row else None
        current_e = current_bill["electric_usage"] if current_bill else None
        current_w = current_bill["water_usage"] if current_bill else None
        previous_e = previous_bill["electric_usage"] if previous_bill else None
        previous_w = previous_bill["water_usage"] if previous_bill else None
        current_ec = current_bill["electric_cents"] if current_bill else 0
        current_wc = current_bill["water_cents"] if current_bill else 0
        previous_ec = previous_bill["electric_cents"] if previous_bill else 0
        previous_wc = previous_bill["water_cents"] if previous_bill else 0
        room_rows.append(
            {
                "room_id": int(room["id"]),
                "property_id": int(room["property_id"]),
                "property_name": room["property_name"],
                "room_no": room["room_no"],
                "tenant_name": room["tenant_name"],
                "current_bill_id": current_bill["id"] if current_bill else None,
                "previous_bill_id": previous_bill["id"] if previous_bill else None,
                "current_period": (
                    f"{current_bill['start_date']} 至 {current_bill['end_date']}"
                    if current_bill
                    else ""
                ),
                "previous_period": (
                    f"{previous_bill['start_date']} 至 {previous_bill['end_date']}"
                    if previous_bill
                    else ""
                ),
                "electric_usage": current_e,
                "previous_electric_usage": previous_e,
                "electric_usage_delta": (
                    round(current_e - previous_e, 2)
                    if current_e is not None and previous_e is not None
                    else None
                ),
                "electric_usage_rate": (
                    (current_e - previous_e) / previous_e
                    if current_e is not None and previous_e not in (None, 0)
                    else None
                ),
                "water_usage": current_w,
                "previous_water_usage": previous_w,
                "water_usage_delta": (
                    round(current_w - previous_w, 2)
                    if current_w is not None and previous_w is not None
                    else None
                ),
                "water_usage_rate": (
                    (current_w - previous_w) / previous_w
                    if current_w is not None and previous_w not in (None, 0)
                    else None
                ),
                "electric_cents": current_ec,
                "previous_electric_cents": previous_ec,
                "electric_delta_cents": current_ec - previous_ec,
                "electric_rate": (
                    (current_ec - previous_ec) / abs(previous_ec) if previous_ec else None
                ),
                "water_cents": current_wc,
                "previous_water_cents": previous_wc,
                "water_delta_cents": current_wc - previous_wc,
                "water_rate": (
                    (current_wc - previous_wc) / abs(previous_wc) if previous_wc else None
                ),
                "total_cents": current_bill["total_cents"] if current_bill else 0,
                "previous_total_cents": previous_bill["total_cents"] if previous_bill else 0,
                "total_delta_cents": (
                    current_bill["total_cents"] - previous_bill["total_cents"]
                    if current_bill and previous_bill
                    else None
                ),
            }
        )

    trend_months = [month_shift(month, offset) for offset in range(-5, 1)]
    trend: list[dict[str, Any]] = []
    for item in trend_months:
        summary_item = _summary_for_month(conn, item)
        trend.append(
            {
                "month": item,
                "billed_cents": summary_item["billed_cents"],
                "cost_cents": summary_item["cost_cents"],
                "profit_cents": summary_item["profit_cents"],
            }
        )

    costs = [
        {
            "id": int(row["id"]),
            "property_id": int(row["property_id"]),
            "property_name": next(
                (item["property_name"] for item in rows if item["property_id"] == row["property_id"]),
                "",
            ),
            "ledger_month": row["ledger_month"],
            "cost_type": row["cost_type"],
            "name": row["name"],
            "amount_cents": int(row["amount_cents"]),
            "note": row["note"],
        }
        for row in conn.execute(
            "SELECT * FROM costs WHERE ledger_month = ? ORDER BY property_id, cost_type, id",
            (month,),
        )
    ]
    return {
        "month": month,
        "previous_month": previous_month,
        "summary": summary,
        "previous_summary": previous_summary,
        "properties": rows,
        "rooms": room_rows,
        "trend": trend,
        "costs": costs,
    }


def upsert_cost(conn: sqlite3.Connection, payload: dict[str, Any]) -> dict[str, Any]:
    property_id = int(payload.get("property_id") or 0)
    get_property(conn, property_id)
    month = parse_month(payload.get("ledger_month"))
    cost_type = str(payload.get("cost_type") or "")
    if cost_type not in ("water", "electricity", "other"):
        raise ApiError("成本类型不正确")
    amount_cents = money_to_cents(payload.get("amount"), "成本金额")
    name = str(payload.get("name") or "").strip()
    if cost_type == "water":
        name = "水成本"
    elif cost_type == "electricity":
        name = "电成本"
    if not name:
        name = "其他成本"
    note = str(payload.get("note") or "").strip()
    timestamp = now_iso()
    requested_id = payload.get("id")
    if requested_id:
        existing_id = conn.execute("SELECT id FROM costs WHERE id = ?", (int(requested_id),)).fetchone()
        if not existing_id:
            raise ApiError("成本记录不存在", 404)
        conn.execute(
            "UPDATE costs SET property_id = ?, ledger_month = ?, cost_type = ?, name = ?, "
            "amount_cents = ?, note = ?, updated_at = ? WHERE id = ?",
            (property_id, month, cost_type, name, amount_cents, note, timestamp, int(requested_id)),
        )
        log_activity(conn, "cost_update", "property", property_id, f"{month} {name} {amount_cents}")
        conn.commit()
        row = conn.execute("SELECT * FROM costs WHERE id = ?", (int(requested_id),)).fetchone()
        return {
            "id": int(row["id"]),
            "property_id": int(row["property_id"]),
            "ledger_month": row["ledger_month"],
            "cost_type": row["cost_type"],
            "name": row["name"],
            "amount_cents": int(row["amount_cents"]),
            "note": row["note"],
        }
    existing = None
    if cost_type in ("water", "electricity"):
        existing = conn.execute(
            "SELECT * FROM costs WHERE property_id = ? AND ledger_month = ? AND cost_type = ?",
            (property_id, month, cost_type),
        ).fetchone()
    if existing:
        conn.execute(
            "UPDATE costs SET name = ?, amount_cents = ?, note = ?, updated_at = ? WHERE id = ?",
            (name, amount_cents, note, timestamp, existing["id"]),
        )
        cost_id = int(existing["id"])
    else:
        cursor = conn.execute(
            "INSERT INTO costs(property_id, ledger_month, cost_type, name, amount_cents, note, "
            "created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (property_id, month, cost_type, name, amount_cents, note, timestamp, timestamp),
        )
        cost_id = int(cursor.lastrowid)
    log_activity(conn, "cost", "property", property_id, f"{month} {name} {amount_cents}")
    conn.commit()
    row = conn.execute("SELECT * FROM costs WHERE id = ?", (cost_id,)).fetchone()
    return {
        "id": int(row["id"]),
        "property_id": int(row["property_id"]),
        "ledger_month": row["ledger_month"],
        "cost_type": row["cost_type"],
        "name": row["name"],
        "amount_cents": int(row["amount_cents"]),
        "note": row["note"],
    }


def delete_cost(conn: sqlite3.Connection, cost_id: int) -> None:
    row = conn.execute("SELECT * FROM costs WHERE id = ?", (cost_id,)).fetchone()
    if not row:
        raise ApiError("成本记录不存在", 404)
    conn.execute("DELETE FROM costs WHERE id = ?", (cost_id,))
    log_activity(conn, "delete_cost", "property", int(row["property_id"]), str(cost_id))
    conn.commit()


def export_backup(conn: sqlite3.Connection) -> bytes:
    tmp_dir = Path(tempfile.mkdtemp(prefix=".rental-backup-", dir=str(BASE_DIR / "data")))
    db_copy = tmp_dir / "rental.db"
    try:
        target = sqlite3.connect(str(db_copy))
        try:
            conn.backup(target)
        finally:
            target.close()
        manifest = {
            "format": "rental-backup-v1",
            "created_at": now_iso(),
            "app": "出租房收租管理系统",
        }
        output = io.BytesIO()
        with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2))
            archive.write(db_copy, "rental.db")
        return output.getvalue()
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


def restore_backup(db_path: Path | str, payload: bytes) -> None:
    path = Path(db_path)
    tmp_dir = Path(tempfile.mkdtemp(prefix=".rental-restore-", dir=str(BASE_DIR / "data")))
    db_candidate = tmp_dir / "rental.db"
    try:
        with zipfile.ZipFile(io.BytesIO(payload)) as archive:
            names = set(archive.namelist())
            if "rental.db" not in names or "manifest.json" not in names:
                raise ApiError("备份文件格式不正确")
            manifest = json.loads(archive.read("manifest.json").decode("utf-8"))
            if manifest.get("format") != "rental-backup-v1":
                raise ApiError("备份版本不受支持")
            db_candidate.write_bytes(archive.read("rental.db"))

        test_conn = sqlite3.connect(str(db_candidate))
        try:
            integrity = test_conn.execute("PRAGMA integrity_check").fetchone()[0]
            if integrity != "ok":
                raise ApiError("备份数据库完整性检查失败")
            tables = {
                row[0]
                for row in test_conn.execute(
                    "SELECT name FROM sqlite_master WHERE type = 'table'"
                )
            }
            required = {"settings", "properties", "rooms", "bills", "payments", "costs"}
            if not required.issubset(tables):
                raise ApiError("备份缺少必要数据表")
        finally:
            test_conn.close()

        path.parent.mkdir(parents=True, exist_ok=True)
        safe_copy = path.with_suffix(".restore.tmp")
        shutil.copyfile(db_candidate, safe_copy)
        os.replace(safe_copy, path)
        for suffix in ("-wal", "-shm"):
            sidecar = Path(str(path) + suffix)
            if sidecar.exists():
                sidecar.unlink()
        init_db(path)
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


def _demo_bill(
    conn: sqlite3.Connection,
    room: sqlite3.Row,
    start: date,
    end: date,
    issue: date,
    ledger_month: str,
    rent_cents: int,
    prev_e: int,
    curr_e: int,
    e_rate: int,
    prev_w: int,
    curr_w: int,
    w_rate: int,
    *,
    other_name: str = "",
    other_cents: int = 0,
) -> int:
    values = {
        "rent_cents": rent_cents,
        "prev_electric_x100": prev_e,
        "current_electric_x100": curr_e,
        "electric_rate_cents": e_rate,
        "prev_water_x100": prev_w,
        "current_water_x100": curr_w,
        "water_rate_cents": w_rate,
        "other1_cents": other_cents,
    }
    calculated = calculate_bill_values(values)
    timestamp = now_iso()
    cursor = conn.execute(
        """
        INSERT INTO bills(
            receipt_no, room_id, property_id, property_name, room_no, tenant_name,
            start_date, end_date, issue_date, ledger_month,
            rent_cents, prev_electric_x100, current_electric_x100, electric_rate_cents,
            prev_water_x100, current_water_x100, water_rate_cents,
            electric_cents, water_cents, other1_name, other1_cents, total_cents, status,
            created_at, updated_at, confirmed_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'confirmed', ?, ?, ?)
        """,
        (
            None,
            int(room["id"]),
            int(room["property_id"]),
            room["property_name"],
            room["room_no"],
            room["tenant_name"],
            start.isoformat(),
            end.isoformat(),
            issue.isoformat(),
            ledger_month,
            rent_cents,
            prev_e,
            curr_e,
            e_rate,
            prev_w,
            curr_w,
            w_rate,
            calculated["electric_cents"],
            calculated["water_cents"],
            other_name,
            other_cents,
            calculated["total_cents"],
            timestamp,
            timestamp,
            timestamp,
        ),
    )
    bill_id = int(cursor.lastrowid)
    receipt_no = _next_receipt_no(conn)
    conn.execute("UPDATE bills SET receipt_no = ? WHERE id = ?", (receipt_no, bill_id))
    return bill_id


def seed_demo(conn: sqlite3.Connection) -> None:
    count = conn.execute("SELECT COUNT(*) AS count FROM properties").fetchone()["count"]
    if int(count or 0) > 0:
        raise ApiError("当前已有房源数据，不能重复载入示例", 409)
    conn.execute(
        "INSERT INTO settings(key, value) VALUES ('next_receipt_no', '351') "
        "ON CONFLICT(key) DO UPDATE SET value = '351'"
    )
    timestamp = now_iso()
    properties = {}
    for name, address, order in (
        ("新村", "新村住宅区", 1),
        ("大路12号", "大路12号", 2),
    ):
        cursor = conn.execute(
            "INSERT INTO properties(name, address, note, sort_order, created_at, updated_at) "
            "VALUES (?, ?, '', ?, ?, ?)",
            (name, address, order, timestamp, timestamp),
        )
        properties[name] = int(cursor.lastrowid)

    room_data = [
        ("新村", "402", "张先生", 300, 1910, 1965, 56, 60, ""),
        ("新村", "403", "李女士", 280, 937, 1197, 110, 116, ""),
        ("新村", "404", "王先生", 280, 2320, 2521, 592, 596, "清洁费"),
        ("新村", "405", "陈女士", 500, 943, 1125, 477, 481, ""),
        ("新村", "501", "刘先生", 260, 3474, 3646, 537, 541, "维修费"),
        ("新村", "502", "赵女士", 200, 1125, 1137, 199, 204, ""),
        ("新村", "503", "周先生", 240, 5021, 5182, 44, 48, ""),
        ("大路12号", "301", "吴女士", 260, 724, 1242, 16, 18, ""),
        ("大路12号", "201", "郑先生", 200, 1660, 1901, 398, 402, ""),
        ("大路12号", "202", "孙女士", 200, 245, 248, 604, 608, ""),
        ("大路12号", "203", "林先生", 200, 801, 874, 555, 559, ""),
        ("大路12号", "401", "何女士", 260, 86, 132, 30, 34, ""),
        ("大路12号", "402", "高先生", 200, 330, 368, 331, 335, ""),
    ]
    room_rows: list[sqlite3.Row] = []
    for index, (property_name, room_no, tenant, rent, current_e, raw_curr_e, prev_w, curr_w, other_name) in enumerate(room_data):
        previous_e = current_e - 45
        mid_e = current_e
        cursor = conn.execute(
            """
            INSERT INTO rooms(
                property_id, room_no, tenant_name, phone, rent_cents,
                electric_rate_cents, water_rate_cents, billing_day, status, note,
                sort_order, created_at, updated_at
            ) VALUES (?, ?, ?, '', ?, 100, 500, 19, 'rented', '', ?, ?, ?)
            """,
            (
                properties[property_name],
                room_no,
                tenant,
                int(rent * 100),
                index,
                timestamp,
                timestamp,
            ),
        )
        room_rows.append(get_room(conn, int(cursor.lastrowid)))

    previous_start = date(2026, 8, 19)
    previous_end = date(2026, 9, 18)
    current_start = date(2026, 9, 19)
    current_end = date(2026, 10, 18)
    current_bill_ids: list[int] = []
    for index, room in enumerate(room_rows):
        mid_e = int(room_data[index][4])
        current_e = int(room_data[index][5])
        first_e = max(0, mid_e - 42)
        mid_w = int(room_data[index][6])
        curr_w = int(room_data[index][7])
        first_w = max(0, mid_w - 2)
        rent_cents = int(room["rent_cents"])
        previous_id = _demo_bill(
            conn,
            room,
            previous_start,
            previous_end,
            date(2026, 9, 6),
            "2026-09",
            rent_cents,
            first_e * 100,
            mid_e * 100,
            100,
            first_w * 100,
            mid_w * 100,
            500,
        )
        other_name = room_data[index][8]
        other_cents = 3000 if other_name == "维修费" else (2000 if other_name else 0)
        current_id = _demo_bill(
            conn,
            room,
            current_start,
            current_end,
            date(2026, 10, 6),
            "2026-10",
            rent_cents,
            mid_e * 100,
            current_e * 100,
            100,
            mid_w * 100,
            curr_w * 100,
            500,
            other_name=other_name,
            other_cents=other_cents,
        )
        current_bill_ids.append(current_id)
        previous_total = int(
            conn.execute(
                "SELECT total_cents FROM bills WHERE id = ?", (previous_id,)
            ).fetchone()["total_cents"]
        )
        conn.execute(
            "INSERT INTO payments(bill_id, amount_cents, paid_at, method, note, created_at) "
            "VALUES (?, ?, ?, '微信', '', ?)",
            (previous_id, previous_total, date(2026, 9, 20).isoformat(), timestamp),
        )
        if index < 8:
            total = conn.execute(
                "SELECT total_cents FROM bills WHERE id = ?", (current_id,)
            ).fetchone()["total_cents"]
            conn.execute(
                "INSERT INTO payments(bill_id, amount_cents, paid_at, method, note, created_at) "
                "VALUES (?, ?, ?, '微信', '', ?)",
                (current_id, int(total), date(2026, 10, 7).isoformat(), timestamp),
            )
        elif index < 11:
            conn.execute(
                "INSERT INTO payments(bill_id, amount_cents, paid_at, method, note, created_at) "
                "VALUES (?, ?, ?, '微信', '', ?)",
                (current_id, rent_cents // 2, date(2026, 10, 8).isoformat(), timestamp),
            )

    for property_name, electricity, water, other in (
        ("新村", 43000, 21000, 5000),
        ("大路12号", 28000, 13500, 0),
    ):
        for month, factor in (("2026-09", 0.9), ("2026-10", 1.0)):
            for cost_type, amount, name in (
                ("electricity", int(electricity * factor), "电成本"),
                ("water", int(water * factor), "水成本"),
            ):
                conn.execute(
                    "INSERT INTO costs(property_id, ledger_month, cost_type, name, amount_cents, "
                    "note, created_at, updated_at) VALUES (?, ?, ?, ?, ?, '', ?, ?)",
                    (properties[property_name], month, cost_type, name, amount, timestamp, timestamp),
                )
            if other and month == "2026-10":
                conn.execute(
                    "INSERT INTO costs(property_id, ledger_month, cost_type, name, amount_cents, "
                    "note, created_at, updated_at) VALUES (?, ?, 'other', '零星维修', ?, '', ?, ?)",
                    (properties[property_name], month, other, timestamp, timestamp),
                )
    log_activity(conn, "seed_demo", "system", None, "载入截图示例数据")
    conn.commit()


def pdf_bytes_for_bill(conn: sqlite3.Connection, bill_id: int) -> tuple[bytes, str]:
    bill = get_bill_json(conn, bill_id)
    if bill["status"] != "confirmed":
        raise ApiError("草稿收据不能导出正式 PDF，请先确认", 409)
    settings = get_settings(conn)
    return build_receipt_pdf(bill, settings), suggested_pdf_name(bill)


def combined_pdf_bytes(conn: sqlite3.Connection, bill_ids: list[int]) -> tuple[bytes, str]:
    bills = ordered_bills_for_summary(conn, bill_ids)
    for bill in bills:
        if bill["status"] != "confirmed":
            raise ApiError("所选收据中包含未确认草稿", 409)
    return build_combined_receipts_pdf(bills, get_settings(conn)), "租金收据汇总.pdf"


def zip_pdfs(conn: sqlite3.Connection, bill_ids: list[int]) -> tuple[bytes, str]:
    settings = get_settings(conn)
    output = io.BytesIO()
    used_names: set[str] = set()
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
        for bill_id in bill_ids:
            bill = get_bill_json(conn, bill_id)
            if bill["status"] != "confirmed":
                continue
            name = suggested_pdf_name(bill)
            stem = name[:-4]
            suffix = 2
            while name in used_names:
                name = f"{stem}_{suffix}.pdf"
                suffix += 1
            used_names.add(name)
            archive.writestr(name, build_receipt_pdf(bill, settings))
        if not used_names:
            raise ApiError("没有可导出的已确认收据")
    return output.getvalue(), "租金收据.zip"


def ledger_csv_bytes(conn: sqlite3.Connection, month: str) -> tuple[bytes, str]:
    data = ledger_data(conn, month)
    output = io.StringIO(newline="")
    writer = csv.writer(output)
    writer.writerow(["经营台账", month])
    writer.writerow(
        [
            "房源",
            "房间数",
            "在租数",
            "收据数",
            "房租收入",
            "电费收入",
            "水费收入",
            "其他收入",
            "计费收入",
            "电成本",
            "水成本",
            "其他成本",
            "成本合计",
            "水电差价",
            "经营毛利",
            "毛利率",
            "实收",
            "未收",
        ]
    )
    for row in data["properties"]:
        writer.writerow(
            [
                row["property_name"],
                row["room_count"],
                row["rented_count"],
                row["billed_count"],
                row["rent_cents"] / 100,
                row["electric_income_cents"] / 100,
                row["water_income_cents"] / 100,
                row["other_income_cents"] / 100,
                row["billed_cents"] / 100,
                row["electric_cost_cents"] / 100,
                row["water_cost_cents"] / 100,
                row["other_cost_cents"] / 100,
                row["cost_cents"] / 100,
                row["utility_spread_cents"] / 100,
                row["profit_cents"] / 100,
                "" if row["margin"] is None else round(row["margin"] * 100, 2),
                row["received_cents"] / 100,
                row["outstanding_cents"] / 100,
            ]
        )
    writer.writerow([])
    writer.writerow(["房间水电变化", month])
    writer.writerow(
        [
            "房源",
            "房间",
            "租客",
            "本期用电",
            "上期用电",
            "用电变化",
            "本期电费",
            "电费变化",
            "本期用水",
            "上期用水",
            "用水变化",
            "本期水费",
            "水费变化",
            "本期账单合计",
            "上期账单合计",
        ]
    )
    for row in data["rooms"]:
        writer.writerow(
            [
                row["property_name"],
                row["room_no"],
                row["tenant_name"],
                row["electric_usage"],
                row["previous_electric_usage"],
                row["electric_usage_delta"],
                row["electric_cents"] / 100,
                row["electric_delta_cents"] / 100,
                row["water_usage"],
                row["previous_water_usage"],
                row["water_usage_delta"],
                row["water_cents"] / 100,
                row["water_delta_cents"] / 100,
                row["total_cents"] / 100,
                row["previous_total_cents"] / 100,
            ]
        )
    content = ("\ufeff" + output.getvalue()).encode("utf-8")
    return content, f"经营台账_{month}.csv"
