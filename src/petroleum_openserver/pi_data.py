"""
OSIsoft PI data access - Python port of the VBA PI module.

Uses the same PI SDK COM library the VBA referenced, through pywin32, so it
needs Windows, PI SDK installed, and a Python whose bitness (32/64-bit)
matches the PI SDK install.

    pip install pywin32

Public functions:
    connect(server_name)                              -> PI server object
    get_pi_tag_att(server, tag, attribute)            -> attribute value or "ERROR"
    get_pi_tag_val(server, tag, start, end)           -> time-weighted average or "ERROR"
    get_pi_tag_arr(server, tag, start, end, int_min, get_avg, include_date)
                                                      -> list of rows
    pi_value(pi_variable, reqd_unit, server_name, date, unit_conv)
                                                      -> daily value for "PI:Tag:Unit"
"""
from __future__ import annotations

import datetime as dt
from typing import Callable, Union

ERROR = "ERROR"
DASH = "-"
PT_STRING = 101  # PointType for string (non-numeric) tags

_sdk = None
_servers: dict = {}


def _pisdk():
    """Create the PISDK COM object once, with generated constants."""
    global _sdk
    if _sdk is None:
        from win32com.client import gencache
        _sdk = gencache.EnsureDispatch("PISDK.PISDK")
    return _sdk


def _const(name: str):
    from win32com.client import constants
    return getattr(constants, name)


def connect(server_name: str):
    """PISDK.Servers(name), cached for the session."""
    key = server_name.casefold()
    if key not in _servers:
        srv = _pisdk().Servers(server_name)
        if not srv.Connected:
            srv.Open()
        _servers[key] = srv
    return _servers[key]


def _is_good(pv) -> bool:
    g = pv.IsGood
    return bool(g() if callable(g) else g)


def _to_datetime(v) -> dt.datetime:
    """pywintypes datetime -> naive datetime."""
    return dt.datetime(v.year, v.month, v.day, v.hour, v.minute, v.second)


def _round_to_minute(t: dt.datetime) -> dt.datetime:
    return t.replace(second=0, microsecond=0)


def get_pi_tag_att(server, tag_name: str, tag_att: str):
    """GetPiTagAtt: a point attribute (e.g. 'engunits'), or 'ERROR'."""
    try:
        return server.PIPoints(tag_name).PointAttributes.Item(tag_att).Value
    except Exception:
        return ERROR


def get_pi_tag_val(server, tag_name: str, start_time, end_time):
    """GetPiTagVal: time-weighted average for numeric tags, interpolated value at
    end_time for string tags, or 'ERROR'."""
    try:
        pt = server.PIPoints(tag_name)
        if pt.PointType != PT_STRING:
            pv = pt.Data.Summary(start_time, end_time, _const("astAverage"), _const("cbTimeWeighted"))
            return float(pv.Value)
        return pt.Data.ArcValue(end_time, _const("rtInterpolated")).Value
    except Exception:
        return ERROR


def get_pi_tag_arr(server, tag_name: str, start_time: dt.datetime, end_time: dt.datetime,
                   int_min: int, get_avg: bool, include_date: bool) -> list:
    """GetPiTagArr.

    Numeric tags with get_avg=True: time-weighted averages over int_min-minute
    intervals, each stamped at the END of its interval (so the value is the
    average for the period leading up to the time). Otherwise interpolated
    values every int_min minutes.

    Returns [[time, value], ...] if include_date else [[value], ...].
    Bad values come back as 'ERROR'.
    """
    pt = server.PIPoints(tag_name)
    numeric = pt.PointType != PT_STRING
    pd = pt.Data  # IPIData2 methods are available on the same object via late binding
    interval = f"{int_min}m"

    if numeric and get_avg:
        nvs = pd.Summaries2(start_time - dt.timedelta(minutes=int_min), end_time, interval,
                            _const("asAverage"), _const("cbTimeWeighted"))
        pvs = nvs.Item("Average").Value
    else:
        pvs = pd.InterpolatedValues2(start_time, end_time, interval)

    rows = []
    for i in range(1, pvs.Count + 1):
        item = pvs.Item(i)
        value = item.Value if _is_good(item) else ERROR
        if include_date:
            t = _to_datetime(item.TimeStamp.LocalDate)
            if get_avg:
                t += dt.timedelta(minutes=int_min)
            rows.append([_round_to_minute(t), value])
        else:
            rows.append([value])
    return rows


def _is_number(v) -> bool:
    if isinstance(v, bool) or v is None:
        return False
    try:
        float(v)
        return True
    except (TypeError, ValueError):
        return False


def pi_value(pi_variable: str, reqd_unit: str, server_name: str, date: Union[dt.date, dt.datetime],
             unit_conv: Callable[[str, str, float], float],
             on_error: Callable[[str], None] = None):
    """PIValue: daily time-weighted average for a 'PI:Tag:Unit' variable.

    As in the VBA, the value is the 24 h average for the period ending at
    midnight at the end of `date` (i.e. the whole of that day), converted from
    the tag's unit to reqd_unit. Returns '-' if the value is missing/negative.
    """
    parts = str(pi_variable).split(":")
    if len(parts) != 3:
        msg = f"PI Variable {pi_variable} should be configured as PI:Tag:Unit"
        if on_error:
            on_error(msg)
        raise ValueError(msg)
    _, tag, pi_unit = parts

    start = dt.datetime(date.year, date.month, date.day) + dt.timedelta(days=1)
    rows = get_pi_tag_arr(connect(server_name), tag, start, start, 1440, True, True)
    val = rows[0][1] if rows else None

    if _is_number(val) and float(val) >= 0:
        return unit_conv(pi_unit, reqd_unit, float(val))
    return DASH
