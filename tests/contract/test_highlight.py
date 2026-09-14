from __future__ import annotations

from app.api.highlight import segments

SOURCE = "Invoice INV-1\nTotal 99.00\n"


def _rows(*spans):
    return [
        {"field": field, "start": start, "end": end} for field, start, end in spans
    ]


def test_unhighlighted_source_is_one_segment():
    assert segments(SOURCE, []) == [type(segments(SOURCE, [])[0])(SOURCE)]


def test_segments_reassemble_the_source_exactly():
    marked = segments(SOURCE, _rows(("invoice_number", 8, 13), ("total", 14, 25)))

    assert "".join(segment.text for segment in marked) == SOURCE
    assert [segment.field for segment in marked if segment.field] == ["invoice_number", "total"]


def test_unverified_evidence_is_not_highlighted():
    marked = segments(SOURCE, [{"field": "total", "start": None, "end": None}])

    assert [segment.field for segment in marked] == [None]


def test_overlapping_spans_do_not_duplicate_text():
    marked = segments(SOURCE, _rows(("outer", 0, 13), ("inner", 8, 13)))

    assert "".join(segment.text for segment in marked) == SOURCE
    assert [segment.field for segment in marked if segment.field] == ["outer"]


def test_spans_are_ordered_by_position_not_by_input_order():
    marked = segments(SOURCE, _rows(("total", 14, 25), ("invoice_number", 8, 13)))

    assert [segment.field for segment in marked if segment.field] == ["invoice_number", "total"]
