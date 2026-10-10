import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core import store  # noqa: E402
from core import workflow as wf  # noqa: E402
from core.config import DEFAULT_SETTINGS, Zone, load_wells, zones_for  # noqa: E402
from core.rollup import all_wells_matrices  # noqa: E402


@pytest.fixture
def env(monkeypatch, tmp_path):
    monkeypatch.setattr(store, "DATA", tmp_path)
    return {**DEFAULT_SETTINGS, "mode": "demo"}, load_wells()


def _matched(row, s):
    run, _ = wf.pull(row, 2026, 7, s)
    return wf.gradient_match(run, row, s)


def test_single_zone_export_goes_straight_to_rollup(env):
    s, W = env
    row = W[W.well == "J03-P"].iloc[0]
    wf.export_well(_matched(row, s), row, s, "2026-07", "matched", 5.0)
    table, meta = store.load_exports("demo", "2026-07")["J03-P"]
    assert meta["split_done"] and "J03-P|oil" in table
    m = all_wells_matrices(store.load_exports("demo", "2026-07"), ["J03-P"], table.index)
    assert "J03-P" in m["oil"].columns


def test_multi_zone_waits_for_split_then_uses_edited_factors(env):
    s, W = env
    row = W[W.well == "J66-P"].iloc[0]
    wf.export_well(_matched(row, s), row, s, "2026-07", "mpfm", 5.0)
    table, meta = store.load_exports("demo", "2026-07")["J66-P"]
    assert not meta["split_done"] and not any("|" in c for c in table.columns)
    assert wf.status_for("demo", "2026-07", W.set_index("well").loc[["J66-P"]].reset_index())["split"][0] == "to do"

    z = zones_for(row)
    new = [Zone(z[0].key, z[0].name, 0.7, z[0].label), Zone(z[1].key, z[1].name, 0.3, z[1].label)]
    out, meta = wf.apply_zonal_split("demo", "2026-07", "J66-P", new)
    assert meta["split_done"] and [q["split"] for q in meta["zones"]] == [0.7, 0.3]
    assert (out[f"{z[0].label}|oil"] + out[f"{z[1].label}|oil"] - out["oil"]).abs().max() < 1e-6


def test_match_after_saving_and_reloading_run(env):
    s, W = env
    row = W[W.well == "J03-P"].iloc[0]
    run, _ = wf.pull(row, 2026, 7, s)
    store.save_run("demo", "2026-07", "J03-P", run)
    out = wf.gradient_match(store.load_run("demo", "2026-07", "J03-P"), row, s)
    assert out["match_phase"].notna().all()
