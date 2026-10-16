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


def test_roll_forward_creates_next_month_sheet_without_changing_history(sandbox):
    sep = pd.date_range("2026-09-01", "2026-09-30", freq="D")
    octo = pd.date_range("2026-10-01", "2026-10-31", freq="D")
    factors.add_change("J03-P", "liquid", 0.95, "2026-09-06", "MPFM recalibrated", old_value=0.9)
    factors.add_change("J03-P", "liquid", 0.97, "2026-11-03", "future change")       # not carried into October
    nxt, new, preview = factors.preview_roll_forward("2026-09")
    assert nxt == "2026-10" and [(c["well"], c["old"], c["new"]) for c in preview] == [("J03-P", "0.9", "0.95")]
    factors.roll_forward("2026-09", "month end")
    assert config.sheet_for_month("2026-10")[1] == "2026-10"
    assert config.sheet_for_month("2026-09")[1] is None                               # September keeps wells.csv
    sep_row = config.load_wells("2026-09").set_index("well").loc["J03-P"]
    oct_row = config.load_wells("2026-10").set_index("well").loc["J03-P"]
    assert sep_row["liquid_factor"] == 0.9 and oct_row["liquid_factor"] == 0.95
    f_sep = factors.daily_factors(sep_row.rename("x").to_frame().T.assign(well="J03-P").iloc[0], sep)
    assert f_sep.loc["2026-09-05", "f_liquid"] == 0.9 and f_sep.loc["2026-09-06", "f_liquid"] == 0.95
    # editing October's sheet to 1.0 is not overridden by the September change
    W = config.load_wells("2026-10")
    W.loc[W.well == "J03-P", "liquid_factor"] = 1.0
    factors.save_config_sheet(W, "new MPFM", mk="2026-10")
    oct_row = config.load_wells("2026-10").set_index("well").loc["J03-P"]
    f_oct = factors.daily_factors(oct_row.to_frame().T.assign(well="J03-P").iloc[0], octo)
    assert (f_oct["f_liquid"] == 1.0).all()
    assert config.load_wells("2026-09").set_index("well").loc["J03-P", "liquid_factor"] == 0.9   # wells.csv untouched
    assert config.load_wells("2026-12").set_index("well").loc["J03-P", "liquid_factor"] == 1.0   # Oct sheet carries on
    with pytest.raises(ValueError):
        factors.roll_forward("2026-09")                                               # won't overwrite silently
    acts = factors.load_audit()["action"].tolist()
    assert acts.count("new month sheet") == 1 and acts.count("config sheet edit") == 1


def _zones3():
    from core.config import Zone
    return [Zone("UZ", "MH5", 0.2, "W UZ"), Zone("MZ", "MH4", 0.4, "W MZ"), Zone("LZ", "MH2", 0.4, "W LZ")]


def test_closed_icv_gets_no_rate_and_open_zones_prorate_to_100pct():
    idx = pd.date_range("2026-09-01", periods=4, freq="D")
    icv = pd.DataFrame({"icv_uz": [10, 10, 1.5, 0], "icv_mz": [6, 2.0, 2.5, 0], "icv_lz": [8, 8, np.nan, 0]},
                       index=idx)
    eff, closed, note = al.zone_factors(idx, _zones3(), icv, closed_max=2.0)
    assert eff.iloc[0].tolist() == [0.2, 0.4, 0.4] and closed.iloc[0] is None             # all open
    assert np.allclose(eff.iloc[1], [0.2 / 0.6, 0, 0.4 / 0.6]) and closed.iloc[1] == "MZ"  # 2.0 counts as closed
    assert np.allclose(eff.iloc[2], [0, 0.4 / 0.8, 0.4 / 0.8]) and closed.iloc[2] == "UZ"  # no LZ reading = open
    assert eff.iloc[3].tolist() == [0.2, 0.4, 0.4] and "All ICVs" in note.iloc[3]          # all closed: fallback
    exp = pd.DataFrame({"liquid": 1000.0, "wct": 20.0, "gor": 1500.0, "bhp_dev_pct": 0.0, "source": "mpfm"},
                       index=idx)
    t = al.zonal_split(exp, _zones3(), icv, 2.0)
    zone_oil = t[["W UZ|oil", "W MZ|oil", "W LZ|oil"]].sum(axis=1)
    assert np.allclose(zone_oil, t["oil"])                                                 # well total kept
    assert t.loc[idx[1], "W MZ|oil"] == 0 and t.loc[idx[1], "W MZ|factor"] == 0
    assert t["icv_closed"].tolist()[1:3] == ["MZ", "UZ"]


def test_apply_zonal_split_uses_pulled_icv(sandbox):
    from core.config import zones_for
    s = {**DEFAULT_SETTINGS, "mode": "live"}
    row = sandbox[sandbox.well == "J23-P"].iloc[0]
    run, _ = wf.pull(row, 2026, 9, {**s, "mode": "demo"})
    run.loc["2026-09-20":, "icv_lz"] = 0.0                                          # LZ shut from the 20th
    run = wf.manual_match(run, row, {**s, "mode": "demo"})
    store.save_run("live", "2026-09", "J23-P", run)
    wf.export_well(run, row, s, "2026-09", "mpfm", 5.0)
    out, meta = wf.apply_zonal_split("live", "2026-09", "J23-P", zones_for(row), closed_max=2.0)
    lz = [z for z in zones_for(row) if z.key == "LZ"][0].label
    assert (out.loc["2026-09-20":, f"{lz}|oil"] == 0).all() and (out.loc[:"2026-09-19", f"{lz}|oil"] > 0).all()
    zone_cols = [c for c in out.columns if c.endswith("|oil")]
    assert np.allclose(out[zone_cols].sum(axis=1), out["oil"], equal_nan=True)
    assert meta["icv_closed_days"] == 11
