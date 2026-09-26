import openpyxl
import pytest

from petroleum_openserver.exceptions import ProgramTerminated
from petroleum_openserver.gap_naming import (
    gap_riser_name,
    gap_well_name,
    row_in_config,
    tag_col_in_config_ncol,
    zone_status,
)


@pytest.fixture
def workbook():
    wb = openpyxl.Workbook()
    config = wb.active
    config.title = "Configuration"

    config["A1"] = "Well Name"
    config["B1"] = "UZ Oil Rate"  # adjacent header, same row `find_cell` will land on
    config["C1"] = "UZ Water Rate"
    config["A3"] = "J03-01"
    config["B3"] = "J03"
    config["A4"] = "J24-01"
    config["B4"] = "J24"

    config["E1"] = "Riser Name"
    config["E3"] = "RISER-A"
    config["F3"] = "R11"

    validation = wb.create_sheet("Validation")
    validation["A1"] = "Well Name"
    validation["A5"] = "J03-01"
    validation["A6"] = "J24-01"

    validation["C1"] = "UZ ICV"
    validation["C5"] = 5
    validation["C6"] = 0

    validation["D1"] = "UZ Liquid Rate"
    validation["D5"] = 1500
    validation["D6"] = 0

    return wb


def test_gap_well_name_found(workbook):
    assert gap_well_name(workbook["Configuration"], "J03-01") == "J03"
    assert gap_well_name(workbook["Configuration"], "j24-01") == "J24"  # case-insensitive


def test_gap_well_name_missing_raises(workbook):
    with pytest.raises(ProgramTerminated):
        gap_well_name(workbook["Configuration"], "UNKNOWN")


def test_gap_riser_name_found(workbook):
    assert gap_riser_name(workbook["Configuration"], "RISER-A") == "R11"


def test_row_in_config_matches_by_position(workbook):
    assert row_in_config(workbook["Validation"], workbook["Configuration"], 0, "Well") == 0
    assert row_in_config(workbook["Validation"], workbook["Configuration"], 1, "Well") == 1


def test_row_in_config_missing_raises(workbook):
    workbook["Validation"]["A5"] = "NOT-CONFIGURED"
    with pytest.raises(ProgramTerminated):
        row_in_config(workbook["Validation"], workbook["Configuration"], 0, "Well")


def test_tag_col_in_config_ncol(workbook):
    assert tag_col_in_config_ncol(workbook["Configuration"], "UZ Oil Rate") == 1
    assert tag_col_in_config_ncol(workbook["Configuration"], "UZ Water Rate") == 2
    assert tag_col_in_config_ncol(workbook["Configuration"], "Not A Column") is None


def test_zone_status_open_when_icv_set_and_producing(workbook):
    assert zone_status(workbook["Validation"], "UZ", 0) == "Open"


def test_zone_status_closed_when_not_producing(workbook):
    assert zone_status(workbook["Validation"], "UZ", 1) == "Closed"
