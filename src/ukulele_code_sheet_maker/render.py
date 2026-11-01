"""A4縦のベクターPDF。小節単位で折り返し、文字と図の重なりを防ぐ。"""

import os
from pathlib import Path
import tempfile

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen.canvas import Canvas

from .parser import Bar, Form, Sheet, SheetError

BLUE = colors.HexColor("#226793")
GRAY = colors.HexColor("#687780")
PAGE_W, PAGE_H = A4
MARGIN = 36
CONTENT_W = PAGE_W - 2 * MARGIN
ROW_H = 132


def register_font(path: str | None = None) -> str:
    candidates = [Path(path)] if path else [
        Path("C:/Windows/Fonts/msgothic.ttc"),
        Path("/usr/share/fonts/truetype/fonts-japanese-gothic.ttf"),
        Path("/usr/share/fonts/truetype/ipaexg/ipaexg.ttf"),
        Path("/usr/share/fonts/opentype/ipafont-gothic/ipag.ttf"),
    ]
    for candidate in candidates:
        if candidate.is_file():
            try:
                pdfmetrics.registerFont(TTFont("SheetJapanese", str(candidate), subfontIndex=0))
                return "SheetJapanese"
            except Exception as exc:
                raise SheetError(f"日本語フォントを読み込めません: {candidate} ({exc})") from exc
    raise SheetError("日本語TrueTypeフォントが見つかりません。--font でTTF/TTCを指定してください。")


def measure(text, font, size):
    return pdfmetrics.stringWidth(text, font, size)


def bar_width(bar: Bar, sheet: Sheet, font: str, carry: str | None = None) -> float:
    beats = sheet.meter[0]
    inner = 65.0
    for event in bar.events:
        need = max(14, measure(event.lyric, font, 10) + 5)
        chord = event.value if event.value != "-" else carry if event.start == 0 else None
        if chord:
            form = sheet.forms[chord]
            need = max(need, 55, measure(form.label, font, 12) + 8)
        inner = max(inner, need * beats / float(event.duration))
    for event in bar.strokes:
        inner = max(inner, 13 * beats / float(event.duration))
    width = inner + 26
    if width > CONTENT_W:
        raise SheetError(f"{bar.line}行: 1小節が印刷幅を超えます。歌詞を短くするか、拍の分割を減らしてください。")
    return width


def diagram(canvas: Canvas, form: Form, x: float, top: float, font: str):
    """左からG C E A。ナットを上にし、開放弦と消音弦を明示する。"""
    pressed = [v for v in form.frets if v is not None and v > 0]
    start = min(pressed) if pressed and max(pressed) > 4 else 1
    count = max(4, max(pressed, default=0) - start + 1)
    fret_h = 40 / count
    canvas.setFillColor(colors.black)
    canvas.setStrokeColor(colors.black)
    canvas.setFont(font, 12)
    canvas.drawString(x, top + 18, form.label)
    grid_x = x + 9
    canvas.setLineWidth(0.45)
    for string in range(4):
        sx = grid_x + string * 10
        canvas.line(sx, top, sx, top - 40)
    for fret in range(count + 1):
        canvas.setLineWidth(1.7 if fret == 0 and start == 1 else 0.45)
        canvas.line(grid_x, top - fret * fret_h, grid_x + 30, top - fret * fret_h)
    if start > 1:
        canvas.setFont("Helvetica", 6)
        canvas.drawRightString(grid_x - 3, top - fret_h / 2 - 2, str(start))
    for string, fret in enumerate(form.frets):
        sx = grid_x + string * 10
        canvas.setLineWidth(0.7)
        if fret is None:
            canvas.line(sx - 2, top + 3, sx + 2, top + 7)
            canvas.line(sx - 2, top + 7, sx + 2, top + 3)
        elif fret == 0:
            canvas.circle(sx, top + 5, 2, fill=0, stroke=1)
        else:
            canvas.circle(sx, top - (fret - start + 0.5) * fret_h, min(2.8, fret_h * .4), fill=1, stroke=0)
    canvas.setFont("Helvetica", 6)
    canvas.setFillColor(GRAY)
    for n, name in enumerate("GCEA"):
        canvas.drawCentredString(grid_x + n * 10, top - 49, name)


def stroke(canvas, symbol, x, y):
    canvas.setStrokeColor(colors.black)
    canvas.setLineWidth(.9)
    if symbol in {"D", "U"}:
        bottom, top = y - 5, y + 5
        end = bottom if symbol == "D" else top
        back = end + 3 if symbol == "D" else end - 3
        canvas.line(x, bottom, x, top)
        canvas.line(x - 2.5, back, x, end)
        canvas.line(x + 2.5, back, x, end)
    elif symbol == "-":
        path = canvas.beginPath()
        path.moveTo(x - 3, y)
        path.curveTo(x - 1, y + 3, x + 1, y - 3, x + 3, y)
        canvas.drawPath(path)
    elif symbol == "x":
        canvas.line(x - 2, y - 2, x + 2, y + 2)
        canvas.line(x - 2, y + 2, x + 2, y - 2)


def render(sheet: Sheet, output: Path, font_path: str | None = None, bars_per_row: int = 4) -> int:
    font = register_font(font_path)
    widths, carry = {}, None
    for bar in sheet.bars:
        widths[id(bar)] = bar_width(bar, sheet, font, carry)
        for event in bar.events:
            if event.value != "-":
                carry = event.value
    for value, size in [(sheet.title, 19)] + [(item.text, 11) for item in sheet.items if not isinstance(item, Bar) and item.kind == "section"]:
        if measure(value, font, size) > CONTENT_W:
            raise SheetError("タイトルまたはセクション名が長すぎます。短くしてください。")
    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(suffix=".pdf", dir=output.parent)
    os.close(fd)
    try:
        canvas = Canvas(temporary, pagesize=A4, pageCompression=1)
        canvas.setTitle(sheet.title)
        canvas.setAuthor("ukulele-code-sheet-maker")
        page, y, bar_number = 0, 0, 0
        previous = None

        def new_page():
            nonlocal page, y
            if page:
                canvas.showPage()
            page += 1
            canvas.setFillColor(BLUE)
            canvas.setFont(font, 19)
            canvas.drawString(MARGIN, PAGE_H - 50, sheet.title)
            canvas.setFillColor(GRAY)
            canvas.setFont(font, 9)
            tempo = f"   テンポ {sheet.tempo}" if sheet.tempo else ""
            canvas.drawString(MARGIN, PAGE_H - 70, f"ウクレレ  G C E A   |   {sheet.meter[0]}/{sheet.meter[1]}{tempo}")
            canvas.setStrokeColor(BLUE)
            canvas.setLineWidth(.7)
            canvas.line(MARGIN, PAGE_H - 80, PAGE_W - MARGIN, PAGE_H - 80)
            canvas.setFont(font, 7)
            canvas.drawString(MARGIN, 25, "↓ ダウン   ↑ アップ   〜 伸ばす   × ミュート   ○ 開放弦")
            canvas.drawRightString(PAGE_W - MARGIN, 25, str(page))
            y = PAGE_H - 101

        row = []

        def flush():
            nonlocal y, bar_number, previous
            if not row:
                return
            if y - ROW_H < 42:
                new_page()
            # 少ない小節を過度に引き伸ばさず、通常は段の全幅を利用する。
            total = sum(widths[id(bar)] for bar in row)
            factor = min(1.6, CONTENT_W / total)
            x = MARGIN
            for index, bar in enumerate(row):
                bar_number += 1
                width = widths[id(bar)] * factor
                inner = width - 26
                canvas.setFont("Helvetica", 7)
                canvas.setFillColor(GRAY)
                canvas.drawString(x + 2, y, str(bar_number))
                canvas.setStrokeColor(BLUE)
                canvas.setLineWidth(.6)
                canvas.line(x, y - 7, x, y - 113)
                if bar.repeat_start:
                    canvas.line(x + 3, y - 7, x + 3, y - 113)
                    canvas.setFillColor(BLUE)
                    for dot_y in [y - 58, y - 66]:
                        canvas.circle(x + 7, dot_y, 1.4, stroke=0, fill=1)
                for event in bar.events:
                    ex = x + 13 + inner * float(event.start) / sheet.meter[0]
                    canvas.setFillColor(BLUE)
                    canvas.setFont(font, 10)
                    canvas.drawString(ex, y - 17, event.lyric)
                    if event.value != "-":
                        previous = event.value
                        diagram(canvas, sheet.forms[previous], ex, y - 68, font)
                    elif index == 0 and event.start == 0:
                        # 段頭で和音が継続する場合も押さえ方を確認できるよう再掲。
                        diagram(canvas, sheet.forms[previous], ex, y - 68, font)
                for event in bar.strokes:
                    ex = x + 16 + inner * float(event.start) / sheet.meter[0]
                    stroke(canvas, event.value, ex, y - 30)
                x += width
                if bar.repeat_end:
                    canvas.setStrokeColor(BLUE)
                    canvas.setLineWidth(1.4)
                    canvas.line(x - 3, y - 7, x - 3, y - 113)
                    canvas.setFillColor(BLUE)
                    for dot_y in [y - 58, y - 66]:
                        canvas.circle(x - 7, dot_y, 1.4, stroke=0, fill=1)
                    canvas.setFont("Helvetica", 7)
                    canvas.drawRightString(x - 4, y, f"x{bar.repeat_end}")
            canvas.setStrokeColor(BLUE)
            canvas.setLineWidth(.6)
            canvas.line(x, y - 7, x, y - 113)
            y -= ROW_H
            row.clear()

        new_page()
        pending_page = False
        for item in sheet.items:
            if pending_page and (isinstance(item, Bar) or item.kind == "section"):
                if y != PAGE_H - 101:
                    new_page()
                pending_page = False
            if isinstance(item, Bar):
                if row and (len(row) >= bars_per_row or sum(widths[id(b)] for b in row) + widths[id(item)] > CONTENT_W):
                    flush()
                row.append(item)
            else:
                flush()
                if item.kind == "page":
                    pending_page = True
                elif item.kind == "section":
                    if y - ROW_H - 23 < 42:
                        new_page()
                    canvas.setFont(font, 11)
                    canvas.setFillColor(BLUE)
                    canvas.drawString(MARGIN, y - 3, item.text)
                    y -= 23
        flush()
        canvas.save()
        os.replace(temporary, output)
        return page
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
