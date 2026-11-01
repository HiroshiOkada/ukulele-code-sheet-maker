from fractions import Fraction

import pytest

from ukulele_code_sheet_maker.parser import SheetError, parse


def test_equal_division_and_nested_subdivision():
    sheet = parse('| C | F G7 | C - F (G G7) |')
    assert [e.duration for e in sheet.bars[0].events] == [4]
    assert [e.start for e in sheet.bars[1].events] == [0, 2]
    assert [e.start for e in sheet.bars[2].events] == [0, 1, 2, 3, Fraction(7, 2)]
    assert sum(e.duration for e in sheet.bars[2].events) == 4


def test_lyrics_comments_and_sharp():
    sheet = parse('フォーム F# = 3121\n| F#"空白 # と |" -"続き" | # コメント')
    assert sheet.bars[0].events[0].lyric == "空白 # と |"
    assert sheet.bars[0].events[1].lyric == "続き"


def test_stroke_override_does_not_leak():
    sheet = parse('ストローク: D D D D\n| C | F |\nストローク: | U - | x . |\n| G7 |')
    assert [e.value for e in sheet.bars[0].strokes] == ["U", "-"]
    assert [e.value for e in sheet.bars[1].strokes] == ["x", "."]
    assert [e.value for e in sheet.bars[2].strokes] == ["D"] * 4


def test_repeat_across_lines_and_form():
    sheet = parse('フォーム upper = [5, 4, 3, 3] 表示=C\n|: upper | F |\n| G7 | C :|x3')
    assert sheet.bars[0].repeat_start
    assert sheet.bars[-1].repeat_end == 3
    assert sheet.forms["upper"].frets == (5, 4, 3, 3)
    assert sheet.forms["upper"].label == "C"


@pytest.mark.parametrize("source,message", [
    ('| C F G |', '3項目'),
    ('| - |', '最初'),
    ('| H7 |', '未登録'),
    ('| C"閉じない |', '引用符'),
    ('| C (F G |', '括弧'),
    ('| C ) |', '括弧'),
    ('| C () |', '空'),
    ('| C || F |', '空'),
    ('| C :|', '反復開始'),
    ('|: C |', '反復終了'),
    ('|: C |: F :|', '入れ子'),
    ('|: C :|x1', '反復回数'),
    ('| C | F |\nストローク: | D |', '小節数'),
    ('ストローク: Q\n| C |', 'ストローク'),
    ('フォーム bad = [1,2,3]\n| C |', '4弦'),
    ('拍子: 5/4\n| C |', '拍子'),
    ('テンポ: 0\n| C |', 'テンポ'),
    ('', '小節がありません'),
])
def test_invalid_inputs(source, message):
    with pytest.raises(SheetError, match=message):
        parse(source)


@pytest.mark.parametrize("meter,body,expected", [("3/4", "C F G", 3), ("6/8", "C F", 6), ("2/4", "C G7", 2)])
def test_other_meters(meter, body, expected):
    sheet = parse(f'拍子: {meter}\n| {body} |')
    assert sum(e.duration for e in sheet.bars[0].events) == expected
