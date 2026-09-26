import openpyxl
import pytest

from petroleum_openserver.exceptions import ProgramTerminated
from petroleum_openserver.excel_io import find_cell, is_numeric, iter_down, try_find_cell


@pytest.fixture
def ws():
    wb = openpyxl.Workbook()
    sheet = wb.active
    sheet["A1"] = "Well Name"
    sheet["A5"] = "WELL-01"
    sheet["A6"] = "WELL-02"
    sheet["A7"] = "WELL-03"
    # Option Compare Text in the original module made comparisons case-insensitive.
    sheet["B1"] = "whp"
    return sheet


def test_find_cell_matches_case_insensitively(ws):
    ref = find_cell(ws, "WELL NAME")
    assert ref.row == 1 and ref.col == 1

    ref2 = find_cell(ws, "WHP")
    assert ref2.row == 1 and ref2.col == 2


def test_find_cell_raises_program_terminated_when_missing(ws):
    with pytest.raises(ProgramTerminated):
        find_cell(ws, "Does Not Exist")


def test_try_find_cell_returns_none_when_missing(ws):
    assert try_find_cell(ws, "Does Not Exist") is None


def test_ref_offset_and_value_roundtrip(ws):
    ref = find_cell(ws, "Well Name").offset(4, 0)
    assert ref.value == "WELL-01"
    ref.value = "RENAMED"
    assert ws["A5"].value == "RENAMED"


def test_iter_down_stops_at_first_empty_cell(ws):
    start = find_cell(ws, "Well Name").offset(4, 0)
    values = [ref.value for ref in iter_down(start)]
    assert values == ["WELL-01", "WELL-02", "WELL-03"]


@pytest.mark.parametrize(
    "value,expected",
    [
        (1, True),
        (1.5, True),
        ("42", True),
        ("42.5", True),
        ("-", False),
        ("ERROR", False),
        (None, False),
        (True, False),
    ],
)
def test_is_numeric(value, expected):
    assert is_numeric(value) is expected
