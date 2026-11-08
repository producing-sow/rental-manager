from __future__ import annotations

import argparse
import csv
import json
import re
import shutil
import sqlite3
import sys
from collections import Counter, defaultdict
from datetime import date, datetime
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from rental_core import init_db, now_iso


HOUSE_FILE = "房屋资料.csv"
BILL_FILE = "单据明细.csv"
SKIP_ADDRESSES = {"101", "102", "1212", "21", "42", "4545", "6"}
PROPERTY_ORDER = ("新村", "大路12号", "沙岗路", "其他房源")
PROPERTY_ADDRESSES = {
    "新村": "新村",
    "大路12号": "大路12号",
    "沙岗路": "沙岗路",
    "其他房源": "旧系统其他房源",
}
EXTRA_FIELDS = (
    ("燃气金额", "燃气费"),
    ("卫生费", "卫生费"),
    ("管理费", "管理费"),
    ("电视费", "电视费"),
    ("网费", "网费"),
    ("其他费用", "其他费用"),
)


def parse_date(value: str) -> str:
    text = (value or "").strip()
    for fmt in ("%Y/%m/%d %H:%M:%S", "%Y-%m-%d %H:%M:%S", "%Y/%m/%d", "%Y-%m-%d"):
        try:
            return datetime.strptime(text, fmt).date().isoformat()
        except ValueError:
            continue
    raise ValueError(f"无法解析日期：{value}")


def cents(value: Any) -> int:
    number = Decimal(str(value or "0")).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    return int(number * 100)


def reading(value: Any) -> int:
    return cents(value)


def split_address(address: str) -> tuple[str, str]:
    address = address.strip()
    match = re.match(r"^(大路12号|沙岗路|新村)(.*)$", address)
    if match and match.group(2):
        return match.group(1), match.group(2)
    return "其他房源", address


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def build_plan(csv_dir: Path) -> tuple[dict[str, Any], list[dict[str, Any]], list[dict[str, Any]]]:
    houses = read_csv(csv_dir / HOUSE_FILE)
    all_bills = read_csv(csv_dir / BILL_FILE)
    current_addresses = {row["地址"].strip() for row in houses}
    current_bills = [
        row for row in all_bills if row["住址"].strip() in current_addresses
    ]
    skipped_bills = [
        row for row in all_bills if row["住址"].strip() not in current_addresses
    ]

    bills_by_address: dict[str, list[dict[str, str]]] = defaultdict(list)
    for row in current_bills:
        bills_by_address[row["住址"].strip()].append(row)
    for rows in bills_by_address.values():
        rows.sort(key=lambda item: parse_date(item["租金日期"]))

    latest_month = max(
        parse_date(row["至租金日期"])[:7] for row in current_bills
    ) if current_bills else ""

    rooms: list[dict[str, Any]] = []
    for index, house in enumerate(houses):
        address = house["地址"].strip()
        property_name, room_no = split_address(address)
        address_bills = bills_by_address.get(address, [])
        latest = address_bills[-1] if address_bills else None
        positive_rents = [
            cents(row["房租"]) for row in address_bills if cents(row["房租"]) >= 100
        ]
        default_rent = positive_rents[-1] if positive_rents else 0
        electric_rate = cents(latest["电费单价"]) if latest else 100
        water_rate = cents(latest["水费单价"]) if latest else 500
        if electric_rate <= 0:
            electric_rate = 100
        if water_rate <= 0:
            water_rate = 500
        billing_day = (
            int(parse_date(latest["租金日期"])[-2:]) if latest else 1
        )
        deposit = Decimal(str(house.get("押金") or "0")).quantize(Decimal("0.01"))
        rooms.append(
            {
                "legacy_id": int(house["IDS"]),
                "address": address,
                "property_name": property_name,
                "room_no": room_no,
                "rent_cents": default_rent,
                "electric_rate_cents": electric_rate,
                "water_rate_cents": water_rate,
                "billing_day": max(1, min(28, billing_day)),
                "tenant_name": (latest.get("租户姓名") or "").strip() if latest else "",
                "note": f"旧系统 IDS={house['IDS']}；押金 {deposit:.2f} 元；自 Data.dx 导入",
                "sort_order": index,
                "bill_count": len(address_bills),
                "latest_date": parse_date(latest["租金日期"]) if latest else None,
            }
        )

    negative_bills = [
        row for row in current_bills if cents(row["房租"]) < 0 or cents(row["总金额"] if "总金额" in row else row["合计金额"]) < 0
    ]
    gas_bills = [row for row in current_bills if cents(row["燃气金额"]) != 0]
    extra_counts = Counter()
    for row in current_bills:
        count = sum(1 for field, _ in EXTRA_FIELDS if cents(row[field]) != 0)
        extra_counts[count] += 1

    latest_bills = [
        row for row in current_bills if parse_date(row["至租金日期"])[:7] == latest_month
    ]
    current_month = date.today().strftime("%Y-%m")
    current_month_bills = [
        row for row in current_bills if parse_date(row["至租金日期"])[:7] == current_month
    ]
    latest_total = sum(cents(row["合计金额"]) for row in latest_bills)
    old_total = sum(cents(row["合计金额"]) for row in skipped_bills)
    receipt_numbers = [int(row["单号"]) for row in current_bills if row["单号"].isdigit()]
    plan = {
        "current_rooms": len(houses),
        "rooms_with_bills": sum(1 for item in rooms if item["bill_count"] > 0),
        "rooms_without_bills": [item["address"] for item in rooms if item["bill_count"] == 0],
        "current_bills": len(current_bills),
        "latest_month": latest_month,
        "latest_bill_count": len(latest_bills),
        "latest_total_cents": latest_total,
        "current_month": current_month,
        "current_month_bill_count": len(current_month_bills),
        "current_month_total_cents": sum(
            cents(row["合计金额"]) for row in current_month_bills
        ),
        "skipped_old_bill_count": len(skipped_bills),
        "skipped_old_addresses": sorted(
            {row["住址"].strip() for row in skipped_bills}
        ),
        "skipped_old_total_cents": old_total,
        "negative_bill_count": len(negative_bills),
        "negative_bill_numbers": [row["单号"] for row in negative_bills],
        "gas_bill_count": len(gas_bills),
        "extra_fee_counts": dict(extra_counts),
        "max_receipt_no": max(receipt_numbers) if receipt_numbers else 0,
        "properties": [
            {
                "name": name,
                "rooms": sorted(
                    item["room_no"] for item in rooms if item["property_name"] == name
                ),
            }
            for name in sorted({item["property_name"] for item in rooms})
        ],
    }
    return plan, rooms, current_bills


def apply_import(
    db_path: Path,
    rooms: list[dict[str, Any]],
    bills: list[dict[str, str]],
    *,
    history_paid: bool,
    backup_path: Path | None = None,
) -> dict[str, Any]:
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        existing = conn.execute("SELECT COUNT(*) FROM properties").fetchone()[0]
        existing_bills = conn.execute("SELECT COUNT(*) FROM bills").fetchone()[0]
        if existing or existing_bills:
            raise RuntimeError("目标账本不是空的，已停止导入")
        if backup_path:
            backup_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(db_path, backup_path)

        timestamp = now_iso()
        property_ids: dict[str, int] = {}
        room_ids: dict[str, int] = {}
        for property_name in PROPERTY_ORDER:
            if not any(room["property_name"] == property_name for room in rooms):
                continue
            cursor = conn.execute(
                "INSERT INTO properties(name, address, note, sort_order, created_at, updated_at) "
                "VALUES (?, ?, '自旧软件 Data.dx 导入', ?, ?, ?)",
                (
                    property_name,
                    PROPERTY_ADDRESSES.get(property_name, ""),
                    len(property_ids),
                    timestamp,
                    timestamp,
                ),
            )
            property_ids[property_name] = int(cursor.lastrowid)

        for room in rooms:
            property_name = room["property_name"]
            cursor = conn.execute(
                """
                INSERT INTO rooms(
                    property_id, room_no, tenant_name, phone, rent_cents,
                    electric_rate_cents, water_rate_cents, billing_day, status, note,
                    sort_order, created_at, updated_at
                ) VALUES (?, ?, ?, '', ?, ?, ?, ?, 'rented', ?, ?, ?, ?)
                """,
                (
                    property_ids[property_name],
                    room["room_no"],
                    room["tenant_name"],
                    room["rent_cents"],
                    room["electric_rate_cents"],
                    room["water_rate_cents"],
                    room["billing_day"],
                    room["note"],
                    room["sort_order"],
                    timestamp,
                    timestamp,
                ),
            )
            room_ids[room["address"]] = int(cursor.lastrowid)

        latest_month = max(parse_date(row["至租金日期"])[:7] for row in bills)
        receipt_numbers = [int(row["单号"]) for row in bills if row["单号"].isdigit()]
        imported_bills = 0
        imported_payments = 0
        for row in bills:
            address = row["住址"].strip()
            room_id = room_ids[address]
            room = next(item for item in rooms if item["address"] == address)
            property_name = room["property_name"]
            property_id = property_ids[property_name]
            start_date = parse_date(row["租金日期"])
            end_date = parse_date(row["至租金日期"])
            issue_date = parse_date(row["添加日期"]) if row["添加日期"].strip() else end_date
            ledger_month = end_date[:7]

            extras: list[tuple[str, int]] = []
            for field, label in EXTRA_FIELDS:
                amount = cents(row[field])
                if amount:
                    extras.append((label, amount))
            if len(extras) > 3:
                extras = extras[:2] + [("旧系统其他费用合计", sum(amount for _, amount in extras[2:]))]

            note_parts = []
            if row["备注"].strip():
                note_parts.append(row["备注"].strip())
            note_parts.append(f"旧系统导入，原单号 {row['单号']}")
            note = "；".join(note_parts)
            total_cents = cents(row["合计金额"])

            cursor = conn.execute(
                """
                INSERT INTO bills(
                    receipt_no, room_id, property_id, property_name, room_no, tenant_name,
                    start_date, end_date, issue_date, ledger_month,
                    rent_cents, prev_electric_x100, current_electric_x100, electric_rate_cents,
                    prev_water_x100, current_water_x100, water_rate_cents,
                    electric_cents, water_cents,
                    other1_name, other1_cents, other2_name, other2_cents,
                    other3_name, other3_cents, total_cents, status, note,
                    created_at, updated_at, confirmed_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'confirmed', ?, ?, ?, ?)
                """,
                (
                    f"{int(row['单号']):06d}",
                    room_id,
                    property_id,
                    property_name,
                    room["room_no"],
                    row["租户姓名"].strip(),
                    start_date,
                    end_date,
                    issue_date,
                    ledger_month,
                    cents(row["房租"]),
                    reading(row["电费上月读数"]),
                    reading(row["电费本月读数"]),
                    cents(row["电费单价"]),
                    reading(row["水费上月读数"]),
                    reading(row["水费本月读数"]),
                    cents(row["水费单价"]),
                    cents(row["电费金额"]),
                    cents(row["水费金额"]),
                    extras[0][0] if len(extras) >= 1 else "",
                    extras[0][1] if len(extras) >= 1 else 0,
                    extras[1][0] if len(extras) >= 2 else "",
                    extras[1][1] if len(extras) >= 2 else 0,
                    extras[2][0] if len(extras) >= 3 else "",
                    extras[2][1] if len(extras) >= 3 else 0,
                    total_cents,
                    note,
                    timestamp,
                    timestamp,
                    timestamp,
                ),
            )
            bill_id = int(cursor.lastrowid)
            imported_bills += 1

            if history_paid and total_cents != 0:
                method = "默认已收" if total_cents > 0 else "调整已收"
                payment_note = (
                    "旧系统未记录收款状态，导入时默认已收"
                    if total_cents > 0
                    else "旧系统负数调整单，按调整后结清"
                )
                conn.execute(
                    "INSERT INTO payments(bill_id, amount_cents, paid_at, method, note, created_at) "
                    "VALUES (?, ?, ?, ?, ?, ?)",
                    (bill_id, total_cents, issue_date, method, payment_note, timestamp),
                )
                imported_payments += 1

        next_no = max(receipt_numbers) + 1 if receipt_numbers else 1
        conn.execute(
            "INSERT INTO settings(key, value) VALUES ('next_receipt_no', ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (str(next_no),),
        )
        conn.execute(
            "INSERT INTO activity_log(action, entity_type, entity_id, detail, created_at) "
            "VALUES ('legacy_import', 'system', NULL, ?, ?)",
            (f"自旧软件 Data.dx 导入 {imported_bills} 张收据", timestamp),
        )
        conn.commit()
        return {
            "properties": len(property_ids),
            "rooms": len(room_ids),
            "bills": imported_bills,
            "historical_payments": imported_payments,
            "latest_month": latest_month,
            "next_receipt_no": f"{next_no:06d}",
        }
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="导入旧版 Access 收租数据")
    parser.add_argument("--csv-dir", required=True)
    parser.add_argument("--db", required=True)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--no-history-paid", action="store_true")
    parser.add_argument("--backup", default="")
    args = parser.parse_args()

    csv_dir = Path(args.csv_dir)
    db_path = Path(args.db)
    plan, rooms, bills = build_plan(csv_dir)
    print(json.dumps(plan, ensure_ascii=False, indent=2))
    if not args.apply:
        return
    if not db_path.exists():
        init_db(db_path)
    result = apply_import(
        db_path,
        rooms,
        bills,
        history_paid=not args.no_history_paid,
        backup_path=Path(args.backup) if args.backup else None,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
