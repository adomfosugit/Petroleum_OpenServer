"""PI data pulling.

Replaces the PIAdvCalcDat array formulas in the 'Allocation Worksheet'
(I6:K36, O6:P36): daily time-weighted averages between the first of the month
and the first of the next month, multiplied by a conversion factor.
"""
from __future__ import annotations

from datetime import date

import pandas as pd

from .config import clean_text

# measurement -> (well-table column holding the tag, settings key of the conversion factor)
MEASUREMENTS: dict[str, tuple[str, str]] = {
    "oil": ("oil_tag", "liquid_conv"),
    "gas": ("gas_tag", "gas_conv"),
    "water": ("water_tag", "liquid_conv"),
    "thp": ("thp_tag", "pressure_conv"),
    "bhp": ("bhp_tag", "pressure_conv"),
}
UNITS = {"oil": "stb/d", "gas": "MMscf/d", "water": "stb/d", "thp": "psia", "bhp": "psia"}


def pi_available() -> tuple[bool, str]:
    try:
        import PIconnect  # noqa: F401
        return True, "PIconnect installed"
    except Exception as exc:  # ImportError, or AF SDK missing on the machine
        return False, f"PIconnect not available ({exc.__class__.__name__})"


def month_bounds(year: int, month: int) -> tuple[pd.Timestamp, pd.Timestamp]:
    start = pd.Timestamp(year=year, month=month, day=1)
    return start, start + pd.offsets.MonthBegin(1)


def month_index(year: int, month: int) -> pd.DatetimeIndex:
    start, end = month_bounds(year, month)
    return pd.date_range(start, end - pd.Timedelta(days=1), freq="D", name="date")


def pull_well_month(well_row: pd.Series, year: int, month: int, settings: dict,
                    progress=None) -> tuple[pd.DataFrame, dict[str, str]]:
    """Pull oil, gas, water, THP and BHP for one well for one month.

    Returns a frame indexed by day with columns oil/gas/water/thp/bhp (already
    converted to field units) and a dict of per-measurement warnings.
    """
    import PIconnect as PI
    from PIconnect.PIConsts import CalculationBasis, SummaryType

    PI.PIConfig.DEFAULT_TIMEZONE = settings.get("timezone", "Africa/Accra")
    start, end = month_bounds(year, month)
    idx = month_index(year, month)
    out = pd.DataFrame(index=idx)
    warnings: dict[str, str] = {}

    server_name = clean_text(settings.get("pi_server"))
    server_ctx = PI.PIServer(server=server_name) if server_name else PI.PIServer()
    with server_ctx as server:
        for i, (key, (tag_col, conv_key)) in enumerate(MEASUREMENTS.items()):
            if progress:
                progress(i / len(MEASUREMENTS), f"Pulling {key}")
            tag = clean_text(well_row.get(tag_col))
            if not tag:
                warnings[key] = "No tag configured"
                out[key] = float("nan")
                continue
            points = server.search(tag)
            if not points:
                warnings[key] = f"Tag {tag} not found on {server.server_name}"
                out[key] = float("nan")
                continue
            summ = points[0].summaries(
                start.strftime("%Y-%m-%d %H:%M"),
                end.strftime("%Y-%m-%d %H:%M"),
                settings.get("pi_interval", "1d"),
                SummaryType.AVERAGE,
                CalculationBasis.TIME_WEIGHTED,
            )
            col = summ["AVERAGE"] if "AVERAGE" in summ else summ.iloc[:, 0]
            ser = pd.to_numeric(col, errors="coerce") * float(settings[conv_key])
            ser.index = pd.DatetimeIndex(ser.index)
            if ser.index.tz is not None:
                ser.index = ser.index.tz_localize(None)
            ser = ser.groupby(ser.index.normalize()).mean()
            out[key] = ser.reindex(idx)
            bad = int(out[key].isna().sum())
            if bad:
                warnings[key] = f"{bad} day(s) with no good data"
    if progress:
        progress(1.0, "Done")
    return out, warnings


def read_uploaded(file, year: int, month: int) -> pd.DataFrame:
    """Accept a CSV/XLSX with columns date, oil, gas, water, thp, bhp (field units)."""
    name = getattr(file, "name", "")
    df = pd.read_excel(file) if name.lower().endswith((".xlsx", ".xlsm", ".xls")) else pd.read_csv(file)
    df.columns = [str(c).strip().lower() for c in df.columns]
    if "date" not in df.columns:
        raise ValueError("The file needs a 'date' column.")
    missing = [c for c in MEASUREMENTS if c not in df.columns]
    if missing:
        raise ValueError(f"Missing column(s): {', '.join(missing)}")
    df["date"] = pd.to_datetime(df["date"]).dt.normalize()
    df = df.set_index("date")[list(MEASUREMENTS)].apply(pd.to_numeric, errors="coerce")
    return df.reindex(month_index(year, month))


def first_of_month(d: date) -> date:
    return d.replace(day=1)
