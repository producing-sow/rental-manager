from __future__ import annotations

import io
from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
from typing import Any

from reportlab.lib.colors import Color, HexColor, white
from reportlab.lib.pagesizes import A4, A5, landscape
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.cidfonts import UnicodeCIDFont
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas


INK = HexColor("#263b33")
MUTED = HexColor("#6f776f")
ACCENT = HexColor("#b65f3e")
PAPER = HexColor("#fcfaf4")
PAPER_DARK = HexColor("#f2ede1")
LINE = HexColor("#d8d0c1")
SOFT_LINE = HexColor("#e8e1d4")
POSITIVE = HexColor("#4c7659")

FONT_BODY = "FangSongLocal"
FONT_HEAD = "SimHeiLocal"
FONT_BOLD = "SimHeiLocal"

_FONTS_READY = False


def _register_fonts() -> None:
    global _FONTS_READY, FONT_BODY, FONT_HEAD, FONT_BOLD
    if _FONTS_READY:
        return

    candidates = {
        FONT_BODY: [
            Path("C:/Windows/Fonts/simfang.ttf"),
            Path("C:/Windows/Fonts/NotoSerifSC-VF.ttf"),
        ],
        FONT_HEAD: [
            Path("C:/Windows/Fonts/simhei.ttf"),
            Path("C:/Windows/Fonts/NotoSansSC-VF.ttf"),
        ],
    }
    resolved = {}
    for font_name, paths in candidates.items():
        for path in paths:
            if path.exists():
                pdfmetrics.registerFont(TTFont(font_name, str(path)))
                resolved[font_name] = font_name
                break
    if len(resolved) < len(candidates):
        fallback_name = "STSong-Light"
        pdfmetrics.registerFont(UnicodeCIDFont(fallback_name))
        FONT_BODY = fallback_name
        FONT_HEAD = fallback_name
        FONT_BOLD = fallback_name
    _FONTS_READY = True


def _money(cents: int | None) -> str:
    return f"￥{(int(cents or 0) / 100):,.2f}"


def _number(value: float | int | None) -> str:
    if value is None:
        return "—"
    number = Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    text = format(number, "f").rstrip("0").rstrip(".")
    return text or "0"


def _group_cn(group: int) -> str:
    digits = "零壹贰叁肆伍陆柒捌玖"
    units = ("", "拾", "佰", "仟")
    result: list[str] = []
    zero_pending = False
    for pos in range(3, -1, -1):
        digit = (group // (10**pos)) % 10
        if digit:
            if zero_pending and result:
                result.append("零")
            result.append(digits[digit] + units[pos])
            zero_pending = False
        elif result:
            zero_pending = True
    return "".join(result)


def rmb_upper(cents: int) -> str:
    cents = int(cents or 0)
    if cents == 0:
        return "零元整"

    sign = "负" if cents < 0 else ""
    cents = abs(cents)
    yuan, remainder = divmod(cents, 100)
    jiao, fen = divmod(remainder, 10)

    big_units = ("", "万", "亿", "兆")
    groups: list[int] = []
    value = yuan
    while value:
        groups.append(value % 10000)
        value //= 10000

    pieces: list[str] = []
    for index in range(len(groups) - 1, -1, -1):
        group = groups[index]
        if group == 0:
            if pieces and not pieces[-1].endswith("零"):
                pieces.append("零")
            continue
        if pieces and group < 1000 and not pieces[-1].endswith("零"):
            pieces.append("零")
        pieces.append(_group_cn(group) + big_units[index])

    integer_text = "".join(pieces).replace("零零", "零").rstrip("零")
    if not integer_text:
        integer_text = "零"

    if jiao == 0 and fen == 0:
        return f"{sign}{integer_text}元整"

    decimals: list[str] = []
    if jiao:
        decimals.append("零壹贰叁肆伍陆柒捌玖"[jiao] + "角")
    elif fen:
        decimals.append("零")
    if fen:
        decimals.append("零壹贰叁肆伍陆柒捌玖"[fen] + "分")

    return f"{sign}{integer_text}元{''.join(decimals)}"


def _draw_text(
    c: canvas.Canvas,
    x: float,
    y: float,
    text: str,
    size: float = 9,
    font: str | None = None,
    color: Color = INK,
    align: str = "left",
) -> None:
    font = font or FONT_BODY
    c.setFont(font, size)
    c.setFillColor(color)
    if align == "right":
        c.drawRightString(x, y, str(text))
    elif align == "center":
        c.drawCentredString(x, y, str(text))
    else:
        c.drawString(x, y, str(text))


def _clip_text(text: str, max_chars: int) -> str:
    text = str(text or "")
    if len(text) <= max_chars:
        return text
    return text[: max_chars - 1] + "…"


def _draw_receipt(
    c: canvas.Canvas,
    x0: float,
    y0: float,
    width: float,
    height: float,
    bill: dict[str, Any],
    settings: dict[str, Any],
) -> None:
    c.saveState()
    c.translate(x0, y0)
    c.setFillColor(PAPER)
    c.rect(0, 0, width, height, fill=1, stroke=0)

    margin = 26
    right = width - margin
    top = height - 26

    c.setFillColor(ACCENT)
    c.rect(margin, top - 2, 30, 3, fill=1, stroke=0)
    _draw_text(
        c,
        width / 2,
        top - 22,
        settings.get("receipt_title") or "租金收据",
        21,
        FONT_HEAD,
        INK,
        "center",
    )
    _draw_text(
        c,
        width / 2,
        top - 35,
        "RENT RECEIPT",
        6.5,
        FONT_BODY,
        MUTED,
        "center",
    )
    _draw_text(c, margin, top - 9, f"日期：{bill.get('issue_date', '')}", 8, FONT_BODY, MUTED)
    _draw_text(
        c,
        right,
        top - 9,
        f"No. {bill.get('receipt_no') or '草稿'}",
        8,
        FONT_BODY,
        MUTED,
        "right",
    )

    c.setStrokeColor(LINE)
    c.setLineWidth(0.8)
    c.line(margin, top - 42, right, top - 42)

    info_y = top - 57
    c.setFillColor(PAPER_DARK)
    c.roundRect(margin, info_y - 13, width - margin * 2, 23, 2, fill=1, stroke=0)
    _draw_text(c, margin + 10, info_y - 3, "房屋", 8.5, FONT_HEAD, MUTED)
    _draw_text(
        c,
        margin + 42,
        info_y - 3,
        f"{bill.get('property_name', '')} · {bill.get('room_no', '')}",
        10.5,
        FONT_HEAD,
        INK,
    )
    if settings.get("show_tenant_on_receipt") in ("1", 1, True) and bill.get("tenant_name"):
        _draw_text(c, right - 92, info_y - 3, "租客", 8.5, FONT_HEAD, MUTED)
        _draw_text(
            c,
            right - 10,
            info_y - 3,
            _clip_text(bill.get("tenant_name", ""), 12),
            9.5,
            FONT_BODY,
            INK,
            "right",
        )

    rent_y = top - 82
    c.setFillColor(white)
    c.setStrokeColor(SOFT_LINE)
    c.roundRect(margin, rent_y - 19, width - margin * 2, 30, 2, fill=1, stroke=1)
    _draw_text(c, margin + 10, rent_y - 8, "房租", 9, FONT_HEAD, MUTED)
    _draw_text(
        c,
        margin + 48,
        rent_y - 8,
        f"{bill.get('start_date', '')} 至 {bill.get('end_date', '')}",
        8.8,
        FONT_BODY,
        INK,
    )
    _draw_text(
        c,
        right - 12,
        rent_y - 8,
        _money(bill.get("rent_cents")),
        10.5,
        FONT_HEAD,
        INK,
        "right",
    )

    table_y = top - 126
    columns = [margin, margin + 78, margin + 166, margin + 250, margin + 326, right]
    c.setFillColor(INK)
    c.roundRect(margin, table_y, width - margin * 2, 25, 2, fill=1, stroke=0)
    headers = ("项目", "上月读数", "本月读数", "实用读数", "单价", "金额")
    centers = [
        columns[0] + 32,
        (columns[1] + columns[2]) / 2,
        (columns[2] + columns[3]) / 2,
        (columns[3] + columns[4]) / 2,
        (columns[4] + columns[5]) / 2,
        columns[5] - 12,
    ]
    for index, header in enumerate(headers):
        _draw_text(
            c,
            centers[index],
            table_y + 8,
            header,
            7.8,
            FONT_HEAD,
            white,
            "right" if index == 5 else "center",
        )

    row_height = 27
    rows = [
        (
            "电费",
            bill.get("prev_electric"),
            bill.get("current_electric"),
            bill.get("electric_usage"),
            bill.get("electric_rate"),
            bill.get("electric_cents"),
        ),
        (
            "水费",
            bill.get("prev_water"),
            bill.get("current_water"),
            bill.get("water_usage"),
            bill.get("water_rate"),
            bill.get("water_cents"),
        ),
    ]
    for row_index, row in enumerate(rows):
        row_y = table_y - (row_index + 1) * row_height
        if row_index % 2 == 0:
            c.setFillColor(HexColor("#faf7ef"))
            c.rect(margin, row_y, width - margin * 2, row_height, fill=1, stroke=0)
        c.setStrokeColor(SOFT_LINE)
        c.line(margin, row_y, right, row_y)
        _draw_text(c, margin + 12, row_y + 9, row[0], 8.8, FONT_HEAD, INK)
        _draw_text(c, centers[1], row_y + 9, _number(row[1]), 8.8, FONT_BODY, INK, "center")
        _draw_text(c, centers[2], row_y + 9, _number(row[2]), 8.8, FONT_BODY, INK, "center")
        _draw_text(c, centers[3], row_y + 9, _number(row[3]), 8.8, FONT_BODY, INK, "center")
        rate_text = "—" if row[4] is None else f"{float(row[4]):.2f}"
        _draw_text(c, centers[4], row_y + 9, rate_text, 8.8, FONT_BODY, INK, "center")
        _draw_text(c, right - 12, row_y + 9, _money(row[5]), 9.2, FONT_HEAD, INK, "right")

    table_bottom = table_y - row_height * 2
    c.setStrokeColor(LINE)
    c.line(margin, table_bottom, right, table_bottom)

    other_fees = [item for item in bill.get("other_fees", []) if item.get("name") or item.get("amount_cents")]
    other_y = table_bottom - 23
    if other_fees:
        _draw_text(c, margin, other_y, "其他费用", 8.5, FONT_HEAD, MUTED)
        cursor_x = margin + 60
        for item in other_fees[:3]:
            label = _clip_text(item.get("name") or f"其他费用{item.get('slot', '')}", 13)
            text = f"{label}  {_money(item.get('amount_cents'))}"
            _draw_text(c, cursor_x, other_y, text, 8.3, FONT_BODY, INK)
            cursor_x += 145

    total_y = other_y - 21 if other_fees else table_bottom - 28
    c.setFillColor(PAPER_DARK)
    c.roundRect(margin, total_y - 25, width - margin * 2, 32, 2, fill=1, stroke=0)
    _draw_text(c, margin + 12, total_y - 14, "合计金额", 8.5, FONT_HEAD, MUTED)
    _draw_text(
        c,
        right - 12,
        total_y - 16,
        _money(bill.get("total_cents")),
        17,
        FONT_HEAD,
        ACCENT,
        "right",
    )

    _draw_text(c, margin + 12, total_y - 42, "人民币（大写）", 7.8, FONT_HEAD, MUTED)
    _draw_text(
        c,
        margin + 92,
        total_y - 42,
        rmb_upper(int(bill.get("total_cents") or 0)),
        9,
        FONT_HEAD,
        INK,
    )

    c.setStrokeColor(LINE)
    c.line(margin, 66, right, 66)
    _draw_text(
        c,
        margin,
        53,
        f"开票人：{settings.get('issuer_name') or ''}",
        7.8,
        FONT_BODY,
        MUTED,
    )
    _draw_text(
        c,
        width / 2,
        53,
        f"收款人：{settings.get('payee_name') or ''}",
        7.8,
        FONT_BODY,
        MUTED,
        "center",
    )
    note = bill.get("note") or settings.get("receipt_note") or ""
    _draw_text(
        c,
        right,
        53,
        _clip_text(note, 32),
        7.2,
        FONT_BODY,
        MUTED,
        "right",
    )
    _draw_text(
        c,
        width / 2,
        34,
        "本收据由出租房收租管理系统生成",
        6.5,
        FONT_BODY,
        MUTED,
        "center",
    )
    c.restoreState()


def build_receipt_pdf(
    bill: dict[str, Any],
    settings: dict[str, Any],
    *,
    combined: bool = False,
) -> bytes:
    _register_fonts()
    buffer = io.BytesIO()
    if combined:
        page_width, page_height = A4
        page = canvas.Canvas(buffer, pagesize=A4)
        receipt_width = page_width
        receipt_height = page_height / 2
    else:
        page_width, page_height = landscape(A5)
        page = canvas.Canvas(buffer, pagesize=(page_width, page_height))
        receipt_width = page_width
        receipt_height = page_height

    page.setTitle(f"租金收据 {bill.get('receipt_no') or ''}")
    page.setAuthor(str(settings.get("issuer_name") or "出租房收租管理系统"))
    page.setSubject("租金、电费和水费收据")
    _draw_receipt(page, 0, 0, receipt_width, receipt_height, bill, settings)
    page.showPage()
    page.save()
    return buffer.getvalue()


def build_combined_receipts_pdf(
    bills: list[dict[str, Any]],
    settings: dict[str, Any],
) -> bytes:
    _register_fonts()
    if not bills:
        raise ValueError("没有可导出的收据")

    buffer = io.BytesIO()
    page_width, page_height = A4
    page = canvas.Canvas(buffer, pagesize=A4)
    page.setTitle("租金收据汇总")
    page.setAuthor(str(settings.get("issuer_name") or "出租房收租管理系统"))

    receipt_height = page_height / 2
    for index, bill in enumerate(bills):
        slot = index % 2
        if slot == 0 and index > 0:
            page.showPage()
        y0 = receipt_height if slot == 0 else 0
        _draw_receipt(page, 0, y0, page_width, receipt_height, bill, settings)

    page.showPage()
    page.save()
    return buffer.getvalue()


def suggested_pdf_name(bill: dict[str, Any]) -> str:
    parts = [
        str(bill.get("property_name") or "房源"),
        str(bill.get("room_no") or "房间"),
        f"{bill.get('start_date', '')}至{bill.get('end_date', '')}",
    ]
    if bill.get("tenant_name"):
        parts.append(str(bill["tenant_name"]))
    safe = "_".join(part.replace("/", "-").replace("\\", "-") for part in parts if part)
    return f"{safe}.pdf"


def generated_stamp() -> str:
    return datetime.now().strftime("%Y%m%d%H%M%S")
