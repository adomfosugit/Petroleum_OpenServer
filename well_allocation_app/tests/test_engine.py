import math
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core import allocation as al  # noqa: E402
from core.config import read_wells_csv, zones_for  # noqa: E402

FIXTURE = Path(__file__).parent / "fixtures" / "wells.csv"
from core.prosper import demo_bhp  # noqa: E402
from core.rollup import all_wells_matrices, normalise  # noqa: E402


def test_derived_parameters_match_workbook_row7():
    # 'Allocation Worksheet' row 7: I7, J7, K7 -> L7, N7 with factors L5=1, N5=1
    run = al.empty_run(pd.DatetimeIndex([pd.Timestamp("2026-07-02")]))
    run[["oil", "gas", "water"]] = [3162.5510309649653, 3.6356993230573016, 3.4768607339032678]
    out = al.derive_parameters(run, pd.Series({"liquid_factor": 1, "wct_factor": 1, "gor_factor": 1}))
    assert math.isclose(out["liquid"].iloc[0], 3166.0278916988686)
    assert math.isclose(out["gor"].iloc[0], 1149.6096940285477)
    assert math.isclose(out["wct"].iloc[0], 3.4768607339032678 / 3166.0278916988686 * 100)


def _vba_allocate(f, target, rate, wct, gor, tol=0.05, maxit=200):
    """Literal transcription of the Allocate macro for one row."""
    it = 0
    while True:
        calc = f(rate, wct, gor)
        if abs((calc - target) / target) <= tol:
            return rate, wct, gor, calc
        rate *= target / calc
        if rate <= 0:
            rate = 1
        it += 1
        if it >= maxit:
            break
    it = 0
    while True:
        calc = f(rate, wct, gor)
        if abs((calc - target) / target) <= tol:
            return rate, wct, gor, calc
        gor *= target / calc
        gor = max(gor, 0)
        it += 1
        if it >= maxit:
            break
    it = 0
    while True:
        calc = f(rate, wct, gor)
        if abs((calc - target) / target) <= tol:
            return rate, wct, gor, calc
        wct = min(max(wct * target / calc, 0), 100)
        it += 1
        if it >= maxit:
            break
    return rate, wct, gor, calc


def test_sequential_matches_vba_transcription():
    def f(q, w, g):
        return demo_bhp(8000, 1200, q, w, g)
    for target, q, w, g, tol in [(3000, 5000, 20, 1200, 0.05), (3400, 3000, 10, 1000, 0.01),
                                 (2100, 9000, 30, 1400, 0.005), (5000, 4000, 5, 1100, 0.001)]:
        exp = _vba_allocate(f, target, q, w, g, tol)
        res = al.match_sequential(f, target, q, w, g, tol)
        assert np.allclose([res.liquid, res.wct, res.gor, res.bhp], exp)


def test_binary_chop_converges():
    def f(q, w, g):
        return demo_bhp(8000, 1200, q, w, g)
    target = f(7000, 20, 1200)
    res = al.match_binary_chop(f, target, 5000, 20, 1200, tol=0.001)
    assert res.converged and abs(res.bhp - target) / target < 0.001


def test_zonal_split_template_formulas():
    exp = pd.DataFrame({"liquid": [1000.0], "wct": [20.0], "gor": [1500.0]}, index=[pd.Timestamp("2026-07-01")])
    wells = read_wells_csv(FIXTURE)
    row = wells[wells.well == "J23-P"].iloc[0]
    t = al.zonal_split(exp, zones_for(row))
    assert t["oil"].iloc[0] == 800 and t["water"].iloc[0] == 200
    assert math.isclose(t["gas"].iloc[0], 1.2)
    assert math.isclose(t["J23-P MZ MH4|oil"].iloc[0], 320)
    assert math.isclose(t["J23-P UZ MH4|wct"].iloc[0], 0.2)


def test_normalisation_sums_to_pprs():
    idx = pd.date_range("2026-07-01", periods=2)
    exports = {
        "A": (pd.DataFrame({"A|oil": [100.0, 200.0]}, index=idx), {}),
        "B": (pd.DataFrame({"B|oil": [300.0, 200.0]}, index=idx), {}),
    }
    m = all_wells_matrices(exports, ["A", "B"], idx)
    pprs = pd.DataFrame({"oil": [800.0, 1000.0], "gas": np.nan, "water": np.nan}, index=idx)
    n = normalise(m, pprs)["oil"]
    assert list(n["A"]) == [200.0, 500.0]
    assert np.allclose(n["Total"], pprs["oil"])
