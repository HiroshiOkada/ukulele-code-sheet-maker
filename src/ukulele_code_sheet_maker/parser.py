"""小節を等分する記法の解析。時間は分数で保持する。"""

from dataclasses import dataclass, field
from fractions import Fraction
import re


class SheetError(ValueError):
    """入力位置付きの、利用者向けエラー。"""


@dataclass
class Form:
    label: str
    frets: tuple[int | None, ...]


BUILTINS = {
    "C": "0003", "Cm": "0333", "C7": "0001", "Cmaj7": "0002",
    "D": "2220", "Dm": "2210", "D7": "2223", "Dm7": "2213",
    "E": "4442", "Em": "0432", "E7": "1202", "Em7": "0202",
    "F": "2010", "Fm": "1013", "F7": "2313", "Fmaj7": "2413",
    "G": "0232", "Gm": "0231", "G7": "0212", "Gmaj7": "0222",
    "A": "2100", "Am": "2000", "A7": "0100", "Am7": "0000",
    "B": "4322", "Bm": "4222", "B7": "2322", "Bb": "3211",
    "Bbm": "3111", "Bb7": "1211", "Asus4": "2200", "Gsus4": "0233",
}


@dataclass
class Event:
    value: str
    start: Fraction
    duration: Fraction
    lyric: str = ""


@dataclass
class Bar:
    events: list[Event]
    line: int
    strokes: list[Event] = field(default_factory=list)
    repeat_start: bool = False
    repeat_end: int = 0


@dataclass
class Directive:
    kind: str
    text: str = ""


@dataclass
class Sheet:
    title: str = "ウクレレ・コードシート"
    meter: tuple[int, int] = (4, 4)
    tempo: int | None = None
    forms: dict[str, Form] = field(default_factory=lambda: {
        name: Form(name, tuple(int(n) for n in frets)) for name, frets in BUILTINS.items()
    })
    items: list[Bar | Directive] = field(default_factory=list)

    @property
    def bars(self):
        return [item for item in self.items if isinstance(item, Bar)]


TOKEN = re.compile(r'\s+|"(?:\\["\\]|[^"\\])*"|[()]|[^\s()"]+')


def strip_comment(line: str) -> str:
    """コード名のシャープや引用符内の # はコメントにしない。"""
    quoted = escaped = False
    for i, char in enumerate(line):
        if escaped:
            escaped = False
        elif char == "\\" and quoted:
            escaped = True
        elif char == '"':
            quoted = not quoted
        elif char == "#" and not quoted and (i == 0 or line[i - 1].isspace()):
            return line[:i]
    return line


def sequence(source: str, beats: int, line: int, stroke: bool = False) -> list[Event]:
    tokens, pos = [], 0
    for match in TOKEN.finditer(source):
        if match.start() != pos:
            raise SheetError(f"{line}行: 引用符またはエスケープが不正です。")
        pos = match.end()
        if not match.group().isspace():
            tokens.append(match.group())
    if pos != len(source):
        raise SheetError(f"{line}行: 歌詞の引用符が閉じていません。")
    index = 0

    def read_group(depth=0):
        nonlocal index
        if depth > 4:
            raise SheetError(f"{line}行: 括弧は4段までです。")
        nodes = []
        while index < len(tokens):
            token = tokens[index]
            index += 1
            if token == ")":
                if not depth:
                    raise SheetError(f"{line}行: 対応する開き括弧がありません。")
                break
            if token == "(":
                nodes.append(read_group(depth + 1))
            elif token.startswith('"'):
                if stroke or not nodes or isinstance(nodes[-1], list) or nodes[-1][1]:
                    raise SheetError(f"{line}行: 歌詞はコードまたは - の直後に指定します。")
                nodes[-1] = (nodes[-1][0], re.sub(r'\\(["\\])', r'\1', token[1:-1]))
            else:
                if stroke and token not in {"D", "U", "-", ".", "x"}:
                    raise SheetError(f"{line}行: 不明なストローク {token!r}（D U - . x を使用）。")
                nodes.append((token, ""))
        else:
            if depth:
                raise SheetError(f"{line}行: 括弧が閉じていません。")
        if not nodes:
            raise SheetError(f"{line}行: 空の小節または括弧です。")
        allowed = {2, 4} if depth else {n for n in range(1, beats + 1) if beats % n == 0}
        if len(nodes) not in allowed:
            example = "例: | C - F G | または | C - - G |。" if beats == 4 and not stroke else ""
            raise SheetError(f"{line}行: {len(nodes)}項目では等分できません。許可: {sorted(allowed)}。{example}")
        return nodes

    nodes = read_group()
    result = []

    def flatten(group, start, duration):
        step = duration / len(group)
        for n, node in enumerate(group):
            at = start + n * step
            if isinstance(node, list):
                flatten(node, at, step)
            else:
                result.append(Event(node[0], at, step, node[1]))

    flatten(nodes, Fraction(0), Fraction(beats))
    return result


def split_bars(source: str, line: int):
    """引用符中の縦棒は歌詞として残す。反復記号は境界に属する。"""
    pattern = r'"(?:\\["\\]|[^"\\])*"|\|:|:\|(?:x[0-9]+)?|\|'
    boundaries = [m for m in re.finditer(pattern, source) if not m.group().startswith('"')]
    if len(boundaries) < 2 or source[:boundaries[0].start()].strip() or source[boundaries[-1].end():].strip():
        raise SheetError(f"{line}行: 小節の両端を | で囲んでください。")
    result = []
    for left, right in zip(boundaries, boundaries[1:]):
        body = source[left.end():right.start()].strip()
        if not body:
            raise SheetError(f"{line}行: 空の小節です。")
        count = int(right.group().split("x")[1]) if "x" in right.group() else 2
        if right.group().startswith(":|") and not 2 <= count <= 99:
            raise SheetError(f"{line}行: 反復回数は2〜99です。")
        result.append((body, left.group() == "|:", count if right.group().startswith(":|") else 0))
    if boundaries[0].group().startswith(":|") or boundaries[-1].group() == "|:":
        raise SheetError(f"{line}行: 反復記号の位置が不正です。")
    return result


def parse(text: str) -> Sheet:
    sheet = Sheet()
    default_stroke = None
    last_bars = None
    override_used = repeat_open = False
    previous = None
    for number, raw in enumerate(text.lstrip("\ufeff").splitlines(), 1):
        line = strip_comment(raw).strip()
        if not line:
            continue
        if line.startswith("フォーム "):
            match = re.fullmatch(r"フォーム\s+([^\s=]+)\s*=\s*(\[[^\]]+\]|[0-9x]{4})(?:\s+表示=(\S+))?", line)
            if not match:
                raise SheetError(f"{number}行: フォームの例: フォーム C = 0003")
            name, frets, label = match.groups()
            parts = frets[1:-1].split(",") if frets.startswith("[") else list(frets)
            try:
                values = tuple(None if x.strip() == "x" else int(x) for x in parts)
            except ValueError:
                raise SheetError(f"{number}行: フレットは0〜24またはxです。") from None
            if len(values) != 4 or any(x is not None and not 0 <= x <= 24 for x in values):
                raise SheetError(f"{number}行: G C E A の4弦を0〜24またはxで指定してください。")
            if sheet.bars:
                raise SheetError(f"{number}行: フォーム定義は本文の前に置いてください。")
            sheet.forms[name] = Form(label or name, values)
        elif line.startswith("ストローク:"):
            value = line.split(":", 1)[1].strip()
            if not sheet.bars:
                if "|" in value:
                    raise SheetError(f"{number}行: 共通ストロークには小節線を使いません。")
                default_stroke = (value, number)
            elif last_bars is None or override_used:
                raise SheetError(f"{number}行: 個別ストロークはコード行の直後に1回指定してください。")
            else:
                patterns = split_bars(value, number) if "|" in value else [(value, False, 0)] * len(last_bars)
                if len(patterns) != len(last_bars) or any(a or b for _, a, b in patterns):
                    raise SheetError(f"{number}行: ストロークの小節数をコード行と合わせ、反復記号は省いてください。")
                for bar, (pattern, _, _) in zip(last_bars, patterns):
                    bar.strokes = sequence(pattern, sheet.meter[0], number, True)
                override_used = True
        elif line.startswith("[") and line.endswith("]"):
            sheet.items.append(Directive("section", line[1:-1]))
            last_bars = None
        elif line in {"@改段", "@改ページ"}:
            sheet.items.append(Directive("row" if line == "@改段" else "page"))
            last_bars = None
        elif line.startswith("|"):
            last_bars = []
            override_used = False
            for body, begin, end in split_bars(line, number):
                if begin:
                    if repeat_open:
                        raise SheetError(f"{number}行: 反復の入れ子には未対応です。")
                    repeat_open = True
                if end:
                    if not repeat_open:
                        raise SheetError(f"{number}行: 反復開始 |: がありません。")
                    repeat_open = False
                events = sequence(body, sheet.meter[0], number)
                for event in events:
                    if event.value == "-":
                        if previous is None:
                            raise SheetError(f"{number}行: 最初のコードは - にできません。")
                    elif event.value not in sheet.forms:
                        raise SheetError(f"{number}行: 未登録のコード {event.value!r}。本文の前にフォームを定義してください。")
                    else:
                        previous = event.value
                strokes = sequence(default_stroke[0], sheet.meter[0], default_stroke[1], True) if default_stroke else []
                bar = Bar(events, number, strokes, begin, end)
                sheet.items.append(bar)
                last_bars.append(bar)
        elif ":" in line:
            key, value = (x.strip() for x in line.split(":", 1))
            if sheet.bars:
                raise SheetError(f"{number}行: ヘッダーは本文の前に置いてください。")
            if key == "タイトル":
                sheet.title = value
            elif key == "拍子":
                if value not in {"2/4", "3/4", "4/4", "6/8"}:
                    raise SheetError(f"{number}行: 対応する拍子は2/4・3/4・4/4・6/8です。")
                sheet.meter = tuple(int(x) for x in value.split("/"))
            elif key == "テンポ":
                if not value.isdigit() or not 20 <= int(value) <= 300:
                    raise SheetError(f"{number}行: テンポは20〜300の整数です。")
                sheet.tempo = int(value)
            else:
                raise SheetError(f"{number}行: 不明な設定 {key!r}。")
        else:
            raise SheetError(f"{number}行: 認識できない記法です。")
    if repeat_open:
        raise SheetError("反復終了 :| がありません。")
    if not sheet.bars:
        raise SheetError("コードの小節がありません。")
    return sheet
