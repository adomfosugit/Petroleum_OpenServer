"""Dated factor changes, audit trail, ICV adjustment flags and run resets."""
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core import allocation as al  # noqa: E402
from core import config, factors, store  # noqa: E402
from core import workflow as wf  # noqa: E402
from core.config import DEFAULT_SETTINGS, read_wells_csv  # noqa: E402

FIXTURE = Path(__file__).parent / "fixtures" / "wells.csv"


@pytest.fixture
def sandbox(monkeypatch, tmp_path):
    """Point config, factor, audit and data files at a temp folder."""
    cfg = tmp_path / "config"
    cfg.mkdir()
    monkeypatch.setattr(config, "CONFIG_DIR", cfg)
    monkeypatch.setattr(config, "WELLS_CSV", cfg / "wells.csv")
    monkeypatch.setattr(factors, "CONFIG_DIR", cfg)
    monkeypatch.setattr(factors, "FACTOR_FILE", cfg / "factor_changes.csv")
    monkeypatch.setattr(factors, "AUDIT_FILE", cfg / "audit_log.csv")
    monkeypatch.setattr(factors, "HISTORY_DIR", cfg / "history")
    monkeypatch.setattr(store, "DATA", tmp_path / "data")
    (cfg / "wells.csv").write_text(FIXTURE.read_text())
    return read_wells_csv(FIXTURE)


def test_factor_applies_from_date_onwards(sandbox):
    row = sandbox[sandbox.well == "J03-P"].iloc[0]          # config liquid factor 0.9
    idx = pd.date_range("2026-09-01", "2026-09-30", freq="D")
    factors.add_change("J03-P", "liquid", 0.95, "2026-09-06", "MPFM recalibrated", old_value=0.9)
    f = factors.daily_factors(row, idx)
    assert (f.loc[:"2026-09-05", "f_liquid"] == 0.9).all()
    assert (f.loc["2026-09-06":, "f_liquid"] == 0.95).all()
    assert (f["f_wct"] == 1.0).all()
    # a later change takes over from its own date
    factors.add_change("J03-P", "liquid", 1.0, "2026-09-20", "back to normal")
    f = factors.daily_factors(row, idx)
    assert f.loc["2026-09-19", "f_liquid"] == 0.95 and f.loc["2026-09-20", "f_liquid"] == 1.0
    periods = factors.factor_periods(f)
    assert list(periods["Liquid"]) == [0.9, 0.95, 1.0]


def test_derive_uses_daily_factors_and_refactor_clears_results(sandbox):
    row = sandbox[sandbox.well == "J03-P"].iloc[0]
    s = {**DEFAULT_SETTINGS, "mode": "demo"}
    run, _ = wf.pull(row, 2026, 9, s)
    run = wf.manual_match(run, row, s)
    factors.add_change("J03-P", "liquid", 1.0, "2026-09-06", "test")
    new = wf.refactor(run, row)
    raw = run["oil"] + run["water"]
    assert np.allclose(new.loc[:"2026-09-05", "liquid"], raw[:"2026-09-05"] * 0.9)
    assert np.allclose(new.loc["2026-09-06":, "liquid"], raw["2026-09-06":] * 1.0)
    assert new["match_bhp"].isna().all() and new["bhp_nodal"].isna().all()


def test_factor_change_is_audited_and_removable(sandbox):
    factors.add_change("J23-P", "gor", 1.1, "2026-09-10", "separator test", old_value=1.0)
    with pytest.raises(ValueError):
        factors.add_change("J23-P", "gor", 1.2, "2026-09-11", "  ")      # reason required
    cid = factors.load_changes("J23-P")["id"].iloc[0]
    factors.delete_change(cid, "entered by mistake")
    log = factors.load_audit()
    assert list(log["action"]) == ["factor change", "factor change removed"]
    assert log.iloc[0]["old"] == "1" and log.iloc[0]["new"] == "1.1" and log.iloc[0]["effective_from"] == "2026-09-10"
    assert factors.load_changes("J23-P").empty


def test_config_sheet_save_backs_up_and_logs(sandbox):
    W = config.load_wells()
    edited = W.copy()
    edited.loc[edited.well == "J03-P", "thp_tag"] = "PT-999045.PV"
    edited.loc[edited.well == "J05-P", "liquid_factor"] = 0.97
    done = factors.save_config_sheet(edited, "new THP tag")
    assert {(c["well"], c["field"]) for c in done} == {("J03-P", "THP (psia)"), ("J05-P", "MPFM Liquid Rate Factor")}
    assert config.load_wells().set_index("well").loc["J03-P", "thp_tag"] == "PT-999045.PV"
    assert len(list(factors.HISTORY_DIR.glob("wells_*.csv"))) == 1
    assert (factors.load_audit()["action"] == "config sheet edit").sum() == 2
    with pytest.raises(ValueError):
        factors.save_config_sheet(edited.iloc[0:0], "empty")            # never wipes the sheet
    assert len(config.load_wells()) == len(W)


def test_icv_flags_each_adjustment_once():
    idx = pd.date_range("2026-09-01", periods=6, freq="D")
    run = al.empty_run(idx)
    run["icv_mz"] = [10, 10, 7, 4, 4, 4]          # moved during day 3
    run["icv_mz_min"] = [10, 10, 4, 4, 4, 4]
    run["icv_mz_max"] = [10, 10, 10, 4, 4, 4]
    run["icv_lz"] = [6, 6, 6, 6, 8, 8]            # step on day 5 with no intra-day data
    run["icv_lz_min"] = np.nan
    run["icv_lz_max"] = np.nan
    out = al.flag_icv_moves(run, ["mz", "lz"], 0.5)
    assert out["icv_moved"].dropna().to_dict() == {idx[2]: "MZ", idx[4]: "LZ"}


def test_multi_zone_pull_has_icv_single_zone_does_not(sandbox):
    s = {**DEFAULT_SETTINGS, "mode": "demo"}
    multi = sandbox[sandbox.well == "J23-P"].iloc[0]
    single = sandbox[sandbox.well == "J03-P"].iloc[0]
    r, _ = wf.pull(multi, 2026, 9, s)
    assert r[["icv_uz", "icv_mz", "icv_lz"]].notna().all().all()
    assert r["icv_moved"].notna().sum() == 1
    r1, _ = wf.pull(single, 2026, 9, s)
    assert r1["icv_uz"].isna().all() and r1["icv_moved"].isna().all()
    store.save_run("live", "2026-09", "J23-P", r)
    back = store.load_run("live", "2026-09", "J23-P")
    assert back["icv_moved"].dropna().tolist() == r["icv_moved"].dropna().tolist()


def test_clear_runs_month_or_all(sandbox):
    s = {**DEFAULT_SETTINGS, "mode": "demo"}
    row = sandbox[sandbox.well == "J03-P"].iloc[0]
    for mth in (8, 9):
        run, _ = wf.pull(row, 2026, mth, s)
        store.save_run("live", f"2026-{mth:02d}", "J03-P", run)
        wf.export_well(wf.manual_match(run, row, s), row, {**s, "mode": "live"}, f"2026-{mth:02d}", "mpfm", 5.0)
    assert store.count_saved("live") == {"runs": 2, "exports": 2}
    assert store.clear_runs("live", "2026-09", True, "redo") == {"runs": 1, "exports": 1}
    assert store.count_saved("live") == {"runs": 1, "exports": 1}
    store.clear_runs("live", None, False, "runs only")
    assert store.count_saved("live") == {"runs": 0, "exports": 1}
    assert (factors.load_audit()["action"] == "clear runs").sum() == 2
