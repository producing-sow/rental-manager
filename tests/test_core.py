import tempfile
import unittest
from datetime import date
from pathlib import Path

from receipt_pdf import rmb_upper
from rental_core import (
    add_months,
    add_payment,
    confirm_bill,
    connect,
    create_bill_draft,
    create_property,
    create_room,
    dashboard_data,
    export_backup,
    get_bill_json,
    init_db,
    ledger_csv_bytes,
    ledger_data,
    ordered_bills_for_summary,
    pdf_bytes_for_bill,
    set_bill_payment_status,
    suggested_period,
    update_bill_draft,
    update_room,
    upsert_cost,
)


class RentalCoreTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parent)
        self.db_path = Path(self.temp.name) / "test.db"
        init_db(self.db_path)
        self.conn = connect(self.db_path)
        self.property = create_property(
            self.conn,
            {"name": "测试新村", "address": "测试路 1 号"},
        )
        self.room = create_room(
            self.conn,
            {
                "property_id": self.property["id"],
                "room_no": "402",
                "tenant_name": "张三",
                "rent": 300,
                "electric_rate": 1,
                "water_rate": 5,
                "billing_day": 19,
            },
        )

    def tearDown(self):
        self.conn.close()
        self.temp.cleanup()

    def _create_current_bill(self, payment_status="paid"):
        bill_id, reused = create_bill_draft(
            self.conn,
            self.room["id"],
            {
                "custom_dates": True,
                "start_date": "2026-09-19",
                "end_date": "2026-10-18",
                "issue_date": "2026-10-06",
                "ledger_month": "2026-10",
            },
        )
        self.assertFalse(reused)
        saved = update_bill_draft(
            self.conn,
            bill_id,
            {
                "prev_electric": 1910,
                "current_electric": 1965,
                "prev_water": 60,
                "current_water": 62,
            },
        )
        confirmed = confirm_bill(self.conn, saved["id"], payment_status=payment_status)
        return confirmed

    def test_period_suggestion_and_month_shift(self):
        start, end = suggested_period(date(2026, 10, 6), 19)
        self.assertEqual(start.isoformat(), "2026-09-19")
        self.assertEqual(end.isoformat(), "2026-10-18")
        self.assertEqual(add_months(date(2026, 1, 31), 1), date(2026, 2, 28))

    def test_first_bill_and_next_period_carry_forward(self):
        first = self._create_current_bill()
        self.assertEqual(first["total_cents"], 36500)
        self.assertEqual(first["receipt_no"], "000001")
        self.assertEqual(first["payment_status"], "paid")
        self.assertEqual(first["paid_cents"], 36500)

        next_id, reused = create_bill_draft(self.conn, self.room["id"], {})
        self.assertFalse(reused)
        next_bill = get_bill_json(self.conn, next_id)
        self.assertEqual(next_bill["start_date"], "2026-10-19")
        self.assertEqual(next_bill["end_date"], "2026-11-18")
        self.assertEqual(next_bill["prev_electric"], 1965)
        self.assertEqual(next_bill["prev_water"], 62)
        self.assertEqual(next_bill["rent_cents"], 30000)
        self.assertEqual(next_bill["electric_rate"], 1)
        self.assertEqual(next_bill["water_rate"], 5)
        self.assertEqual(next_bill["status"], "draft")

        reopened_id, reused_again = create_bill_draft(self.conn, self.room["id"], {})
        self.assertTrue(reused_again)
        self.assertEqual(reopened_id, next_id)

    def test_confirm_moves_to_next_pending_room(self):
        second = create_room(
            self.conn,
            {
                "property_id": self.property["id"],
                "room_no": "403",
                "tenant_name": "李四",
                "rent": 280,
                "electric_rate": 1,
                "water_rate": 5,
                "billing_day": 19,
            },
        )
        third = create_room(
            self.conn,
            {
                "property_id": self.property["id"],
                "room_no": "401",
                "tenant_name": "王五",
                "rent": 260,
                "electric_rate": 1,
                "water_rate": 5,
                "billing_day": 19,
            },
        )
        second_draft_id, reused = create_bill_draft(
            self.conn,
            second["id"],
            {
                "custom_dates": True,
                "start_date": "2026-09-19",
                "end_date": "2026-10-18",
                "issue_date": "2026-10-06",
                "ledger_month": "2026-10",
            },
        )
        self.assertFalse(reused)

        first = self._create_current_bill()
        next_room = first["next_room"]
        self.assertEqual(next_room["room_id"], second["id"])
        self.assertEqual(next_room["room_no"], "403")
        self.assertEqual(next_room["tenant_name"], "李四")
        self.assertEqual(next_room["action"], "draft")
        self.assertEqual(next_room["bill_id"], second_draft_id)
        self.assertFalse(next_room["has_history"])
        self.assertEqual(next_room["start_date"], "2026-09-19")
        self.assertEqual(next_room["end_date"], "2026-10-18")

        update_bill_draft(
            self.conn,
            second_draft_id,
            {
                "prev_electric": 100,
                "current_electric": 150,
                "prev_water": 20,
                "current_water": 23,
            },
        )
        second_bill = confirm_bill(self.conn, second_draft_id)
        self.assertEqual(second_bill["next_room"]["room_id"], third["id"])
        self.assertEqual(second_bill["next_room"]["room_no"], "401")
        self.assertEqual(second_bill["next_room"]["action"], "new")

        third_draft_id, _ = create_bill_draft(
            self.conn,
            third["id"],
            {
                "custom_dates": True,
                "start_date": "2026-09-19",
                "end_date": "2026-10-18",
                "issue_date": "2026-10-06",
                "ledger_month": "2026-10",
            },
        )
        update_bill_draft(
            self.conn,
            third_draft_id,
            {
                "prev_electric": 100,
                "current_electric": 140,
                "prev_water": 20,
                "current_water": 22,
            },
        )
        third_bill = confirm_bill(self.conn, third_draft_id)
        self.assertIsNone(third_bill["next_room"])

    def test_other_fee_stays_hidden_until_added(self):
        first = self._create_current_bill()
        self.assertEqual(first["other_fees"], [])
        draft_id, _ = create_bill_draft(self.conn, self.room["id"], {})
        self.assertEqual(get_bill_json(self.conn, draft_id)["other_fees"], [])
        saved = update_bill_draft(
            self.conn,
            draft_id,
            {
                "current_electric": 2000,
                "current_water": 64,
                "other2_name": "维修费",
                "other2": 30,
            },
        )
        self.assertEqual(saved["total_cents"], 37500)
        self.assertEqual(saved["other_fees"][0]["slot"], 2)

    def test_auto_reading_increment_locks_and_carries_edited_value(self):
        update_room(
            self.conn,
            self.room["id"],
            {
                "electric_auto_enabled": True,
                "electric_auto_increment": 12,
                "water_auto_enabled": True,
                "water_auto_increment": 2,
            },
        )
        first = self._create_current_bill()
        self.assertFalse(first["electric_auto_locked"])

        second_id, _ = create_bill_draft(self.conn, self.room["id"], {})
        second = get_bill_json(self.conn, second_id)
        self.assertEqual(second["current_electric"], 1977)
        self.assertEqual(second["current_water"], 64)
        self.assertTrue(second["electric_auto_locked"])
        self.assertTrue(second["water_auto_locked"])

        with self.assertRaisesRegex(Exception, "先点击解锁"):
            update_bill_draft(self.conn, second_id, {"current_electric": 1980})
        update_bill_draft(self.conn, second_id, {"electric_auto_locked": False})
        second = update_bill_draft(
            self.conn,
            second_id,
            {
                "current_electric": 1980,
            },
        )
        self.assertFalse(second["electric_auto_locked"])
        self.assertTrue(second["water_auto_locked"])
        confirm_bill(self.conn, second_id)

        third_id, _ = create_bill_draft(self.conn, self.room["id"], {})
        third = get_bill_json(self.conn, third_id)
        self.assertEqual(third["prev_electric"], 1980)
        self.assertEqual(third["prev_water"], 64)
        self.assertEqual(third["current_electric"], 1992)
        self.assertEqual(third["current_water"], 66)

    def test_negative_usage_is_blocked(self):
        bill_id, _ = create_bill_draft(self.conn, self.room["id"], {"custom_dates": True, "start_date": "2026-09-19", "end_date": "2026-10-18"})
        update_bill_draft(
            self.conn,
            bill_id,
            {
                "prev_electric": 100,
                "current_electric": 90,
                "prev_water": 20,
                "current_water": 21,
            },
        )
        with self.assertRaisesRegex(Exception, "电表读数"):
            confirm_bill(self.conn, bill_id)

    def test_negative_rent_is_allowed_for_adjustments(self):
        bill_id, _ = create_bill_draft(
            self.conn,
            self.room["id"],
            {
                "custom_dates": True,
                "start_date": "2026-09-19",
                "end_date": "2026-10-18",
                "ledger_month": "2026-10",
            },
        )
        update_bill_draft(
            self.conn,
            bill_id,
            {
                "rent": -40,
                "prev_electric": 1910,
                "current_electric": 1965,
                "prev_water": 60,
                "current_water": 62,
            },
        )
        confirmed = confirm_bill(self.conn, bill_id)
        self.assertEqual(confirmed["rent_cents"], -4000)
        self.assertEqual(confirmed["total_cents"], 2500)
        self.assertEqual(confirmed["payment_status"], "paid")
        pdf, _ = pdf_bytes_for_bill(self.conn, bill_id)
        self.assertTrue(pdf.startswith(b"%PDF"))

    def test_ledger_profit_and_comparison(self):
        first = self._create_current_bill(payment_status="unpaid")
        add_payment(
            self.conn,
            first["id"],
            {"amount": 200, "paid_at": "2026-10-08", "method": "微信"},
        )
        upsert_cost(
            self.conn,
            {
                "property_id": self.property["id"],
                "ledger_month": "2026-10",
                "cost_type": "electricity",
                "amount": 40,
            },
        )
        upsert_cost(
            self.conn,
            {
                "property_id": self.property["id"],
                "ledger_month": "2026-10",
                "cost_type": "water",
                "amount": 15,
            },
        )
        ledger = ledger_data(self.conn, "2026-10")
        row = ledger["properties"][0]
        self.assertEqual(row["billed_cents"], 36500)
        self.assertEqual(row["cost_cents"], 5500)
        self.assertEqual(row["profit_cents"], 31000)
        self.assertFalse(row["cost_missing"])
        self.assertEqual(ledger["summary"]["received_cents"], 20000)
        self.assertEqual(ledger["summary"]["outstanding_cents"], 16500)

        dashboard = dashboard_data(self.conn, "2026-10")
        self.assertEqual(dashboard["profit_cents"], 31000)
        self.assertEqual(dashboard["rooms_total"], 1)
        csv_data, csv_name = ledger_csv_bytes(self.conn, "2026-10")
        self.assertTrue(csv_data.startswith(b"\xef\xbb\xbf"))
        self.assertIn("经营台账", csv_name)

    def test_pdf_and_backup(self):
        first = self._create_current_bill()
        pdf, filename = pdf_bytes_for_bill(self.conn, first["id"])
        self.assertTrue(pdf.startswith(b"%PDF"))
        self.assertGreater(len(pdf), 10000)
        self.assertIn("402", filename)
        backup = export_backup(self.conn)
        self.assertGreater(len(backup), 1000)
        self.assertEqual(backup[:2], b"PK")

    def test_summary_order_is_property_then_room_number(self):
        first_property_rooms = []
        for room_no in ("303", "301", "302", "一楼"):
            room = create_room(
                self.conn,
                {
                    "property_id": self.property["id"],
                    "room_no": room_no,
                    "billing_day": 19,
                },
            )
            bill_id, _ = create_bill_draft(
                self.conn,
                room["id"],
                {
                    "custom_dates": True,
                    "start_date": "2026-09-19",
                    "end_date": "2026-10-18",
                    "ledger_month": "2026-10",
                },
            )
            first_property_rooms.append(bill_id)

        other_property = create_property(self.conn, {"name": "第二房源"})
        other_room = create_room(
            self.conn,
            {
                "property_id": other_property["id"],
                "room_no": "201",
                "billing_day": 19,
            },
        )
        other_bill_id, _ = create_bill_draft(
            self.conn,
            other_room["id"],
            {
                "custom_dates": True,
                "start_date": "2026-09-19",
                "end_date": "2026-10-18",
                "ledger_month": "2026-10",
            },
        )

        shuffled = [other_bill_id, first_property_rooms[2], first_property_rooms[3], first_property_rooms[0], first_property_rooms[1]]
        ordered = ordered_bills_for_summary(self.conn, shuffled)
        self.assertEqual(
            [(bill["property_name"], bill["room_no"]) for bill in ordered],
            [
                ("测试新村", "301"),
                ("测试新村", "302"),
                ("测试新村", "303"),
                ("测试新村", "一楼"),
                ("第二房源", "201"),
            ],
        )

    def test_rmb_upper(self):
        self.assertEqual(rmb_upper(35500), "叁佰伍拾伍元整")
        self.assertEqual(rmb_upper(10001), "壹佰元零壹分")
        self.assertEqual(rmb_upper(0), "零元整")

    def test_payment_status_can_toggle(self):
        first = self._create_current_bill()
        unpaid = set_bill_payment_status(self.conn, first["id"], "unpaid")
        self.assertEqual(unpaid["payment_status"], "unpaid")
        self.assertEqual(unpaid["paid_cents"], 0)
        paid = set_bill_payment_status(self.conn, first["id"], "paid")
        self.assertEqual(paid["payment_status"], "paid")
        self.assertEqual(paid["paid_cents"], paid["total_cents"])


if __name__ == "__main__":
    unittest.main()
