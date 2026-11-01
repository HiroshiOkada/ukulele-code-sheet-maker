"""CLIの入出力とエラー表示。"""

import argparse
from pathlib import Path
import sys

from .parser import BUILTINS, SheetError, parse


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="テキストからA4のウクレレ用コードシートPDFを生成します。")
    parser.add_argument("input", nargs="?", type=Path, help="UTF-8の入力ファイル（.ukeなど）")
    parser.add_argument("-o", "--output", type=Path, help="出力PDF（省略時は入力と同じ名前の.pdf）")
    parser.add_argument("--check", action="store_true", help="入力記法のみ検証し、PDFを作成しない")
    parser.add_argument("--font", help="埋め込む日本語TrueTypeフォント（TTF/TTC）")
    parser.add_argument("--bars-per-row", type=int, default=4, choices=range(1, 9), metavar="1-8", help="1段の最大小節数（既定: 4。内容が多ければ自動で減らす）")
    parser.add_argument("--list-chords", action="store_true", help="内蔵コードとG C E A順のフレットを表示")
    args = parser.parse_args(argv)
    if args.list_chords:
        for name, frets in BUILTINS.items():
            print(f"{name:8} {frets}")
        return 0
    if not args.input:
        parser.error("入力ファイルを指定してください。")
    try:
        sheet = parse(args.input.read_text(encoding="utf-8-sig"))
        if args.check:
            print(f"検証OK: {sheet.title} / {len(sheet.bars)}小節")
            return 0
        output = args.output or args.input.with_suffix(".pdf")
        if output.resolve() == args.input.resolve():
            raise SheetError("入力ファイルと出力ファイルは別のパスにしてください。")
        from .render import render
        pages = render(sheet, output, args.font, args.bars_per_row)
        print(f"作成しました: {output}（A4 / {pages}ページ / {len(sheet.bars)}小節）")
        return 0
    except (SheetError, OSError, UnicodeError) as exc:
        print(f"エラー: {exc}", file=sys.stderr)
        return 2
