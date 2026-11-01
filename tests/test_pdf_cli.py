from pathlib import Path

import pytest
from pypdf import PdfReader
from reportlab.lib.pagesizes import A4

from ukulele_code_sheet_maker.cli import main
from ukulele_code_sheet_maker.parser import SheetError, parse
from ukulele_code_sheet_maker.render import render

ROOT = Path(__file__).resolve().parents[1]


def test_sample_a4_embedded_font_and_text(tmp_path):
    sheet = parse((ROOT / "examples/twinkle.uke").read_text(encoding="utf-8"))
    assert len(sheet.bars) == 24
    output = tmp_path / "sample.pdf"
    count = render(sheet, output)
    pdf = PdfReader(output)
    assert len(pdf.pages) == count
    text = "".join(p.extract_text() for p in pdf.pages)
    assert "きらきら星" in text and "見よう" in text
    for page in pdf.pages:
        assert abs(float(page.mediabox.width) - A4[0]) < .01
        assert abs(float(page.mediabox.height) - A4[1]) < .01
        fonts = [ref.get_object() for ref in page["/Resources"]["/Font"].values()]
        assert any("/FontFile2" in f.get("/FontDescriptor", {}) for f in fonts)


def test_automatic_pagination_preserves_all_bars(tmp_path):
    body = '\n'.join(f'| C"小節{i:03}" |' for i in range(80))
    output = tmp_path / "long.pdf"
    pages = render(parse(body), output)
    assert pages >= 4
    text = "".join(p.extract_text() for p in PdfReader(output).pages)
    for i in range(80):
        assert text.count(f"小節{i:03}") == 1


def test_explicit_page_break(tmp_path):
    output = tmp_path / "break.pdf"
    assert render(parse('| C |\n@改ページ\n| F |'), output) == 2


def test_trailing_page_break_does_not_add_blank_page(tmp_path):
    assert render(parse('| C |\n@改ページ'), tmp_path / 'end.pdf') == 1


def test_overflow_does_not_replace_existing_output(tmp_path):
    output = tmp_path / "keep.pdf"
    output.write_bytes(b"existing")
    with pytest.raises(SheetError, match="印刷幅"):
        render(parse('| C"' + '長い歌詞' * 40 + '" |'), output)
    assert output.read_bytes() == b"existing"


def test_cli_check_and_errors(tmp_path, capsys):
    source = tmp_path / "song.uke"
    source.write_text('| C |', encoding="utf-8")
    assert main([str(source), "--check"]) == 0
    assert not source.with_suffix(".pdf").exists()
    assert main([str(source), "-o", str(source)]) == 2
    assert "別のパス" in capsys.readouterr().err
    source.write_text('| C F G |', encoding="utf-8")
    assert main([str(source)]) == 2
    assert "1行" in capsys.readouterr().err
