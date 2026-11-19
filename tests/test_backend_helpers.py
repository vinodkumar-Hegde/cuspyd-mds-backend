"""Provider-free tests for export and analytics helpers."""
from app.operations import safe_cell, score_from_payload


def test_csv_formula_injection():
    for val in ('=1+1','+SUM(2,2)','-4','@A1','   =BAD'):
        assert safe_cell(val).startswith("'")
    assert safe_cell('Normal text')=='Normal text'
    assert safe_cell(['one','two'])=='["one", "two"]'


def test_nested_scores():
    score={'score':8,'correct':2,'wrong':0,'unattempted':1}
    assert score_from_payload(score)['score']==8
    assert score_from_payload({'results':score})['correct']==2
    assert score_from_payload({'wrong':'bad'}) is None
    assert score_from_payload(None) is None
    assert score_from_payload({'score':float('nan'),'correct':0,'wrong':0,'unattempted':0}) is None
