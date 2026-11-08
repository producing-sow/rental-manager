import argparse
import shutil
import sqlite3
from datetime import datetime
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser(description="将历史已确认收据迁移为默认已收")
    parser.add_argument("--db", required=True)
    parser.add_argument("--backup", default="")
    args = parser.parse_args()

    db_path = Path(args.db)
    if args.backup:
        backup = Path(args.backup)
        backup.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(db_path, backup)

    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            """
            SELECT b.id, b.total_cents, b.issue_date
            FROM bills b
            LEFT JOIN payments p ON p.bill_id = b.id
            WHERE b.status = 'confirmed'
              AND b.total_cents <> 0
            GROUP BY b.id
            HAVING COUNT(p.id) = 0
            """
        ).fetchall()
        timestamp = datetime.now().replace(microsecond=0).isoformat()
        for row in rows:
            method = "默认已收" if row["total_cents"] > 0 else "调整已收"
            note = (
                "确认后默认已收（历史数据迁移）"
                if row["total_cents"] > 0
                else "旧系统负数调整单，按调整后结清"
            )
            conn.execute(
                "INSERT INTO payments(bill_id, amount_cents, paid_at, method, note, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (
                    row["id"],
                    row["total_cents"],
                    row["issue_date"],
                    method,
                    note,
                    timestamp,
                ),
            )
        conn.execute(
            "INSERT INTO activity_log(action, entity_type, entity_id, detail, created_at) "
            "VALUES ('default_paid_migration', 'system', NULL, ?, ?)",
            (f"为 {len(rows)} 张已确认收据补记默认已收", timestamp),
        )
        conn.commit()
        print(f"migrated={len(rows)}")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
