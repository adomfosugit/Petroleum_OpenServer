"""Port of the VBA `iPT_UnitConv` global function.

The original macro declared `Dim objUC As New iPT_Utilities.iPT_UnitConv` -
a separate Petex COM component (part of the IPM install, not OpenServer)
used purely for unit conversion so that values typed into the workbook in
whatever unit the field uses could be converted to PROSPER/GAP's "field
units" before being pushed over OpenServer, and back again on the way out.

IMPORTANT: the pasted VBA only showed a wrapper (`iPTUnitConv`) that itself
called `iPT_UnitConv(...)`, not the body of the real conversion routine or
the exact method name on the `iPT_Utilities.iPT_UnitConv` COM object, so
that method name below (`Convert`) is a best guess and MUST be confirmed
against the actual type library on a machine with IPM installed, e.g.:

    import win32com.client
    obj = win32com.client.Dispatch("iPT_Utilities.iPT_UnitConv")
    print(win32com.client.gencache.EnsureDispatch(obj))  # inspect ._prop_map_get_/methods

`SimpleUnitConverter` is a small pure-Python fallback covering the handful
of unit strings actually used in the sheet headers referenced by the VBA
(psi/psig/psia, stb/d, mmscf/d, scf/stb, %, degF). It exists so the rest of
this package can be imported and unit-tested on a non-Windows machine
without IPM installed; it is NOT a substitute for `PetexUnitConverter` in
production, and does not claim to cover every unit PROSPER/GAP support.
"""

from __future__ import annotations

from typing import Protocol


class UnitConversionError(RuntimeError):
    pass


class UnitConverter(Protocol):
    def convert(self, from_unit: str, to_unit: str, value: float) -> float: ...


class PetexUnitConverter:
    """Wraps the real `iPT_Utilities.iPT_UnitConv` COM component. Windows + IPM only."""

    _CANDIDATE_METHODS = ("Convert", "ConvertUnit", "UnitConvert", "ConvertValue")

    def __init__(self) -> None:
        self._obj = None
        self._method_name: str | None = None

    def _ensure(self):
        if self._obj is None:
            try:
                import win32com.client
            except ImportError as exc:  # pragma: no cover - Windows only
                raise UnitConversionError(
                    "pywin32 is required for PetexUnitConverter (Windows + IPM only)."
                ) from exc
            self._obj = win32com.client.Dispatch("iPT_Utilities.iPT_UnitConv")
        return self._obj

    def convert(self, from_unit: str, to_unit: str, value: float) -> float:
        if not from_unit or not to_unit or from_unit == to_unit:
            return value
        obj = self._ensure()
        if self._method_name is not None:
            return getattr(obj, self._method_name)(from_unit, to_unit, value)
        for name in self._CANDIDATE_METHODS:
            method = getattr(obj, name, None)
            if method is None:
                continue
            try:
                result = method(from_unit, to_unit, value)
            except Exception:  # noqa: BLE001 - try the next candidate name
                continue
            self._method_name = name
            return result
        raise UnitConversionError(
            f"Could not find a working conversion method on iPT_Utilities.iPT_UnitConv "
            f"(tried {self._CANDIDATE_METHODS}). Inspect the COM object's type library "
            f"and set PetexUnitConverter._method_name explicitly."
        )


# (from_unit, to_unit) -> multiplicative factor, applied as value * factor.
# Additive conversions (degF<->degC) are handled separately below.
_LINEAR_FACTORS: dict[tuple[str, str], float] = {
    ("psi", "psig"): 1.0,
    ("psig", "psi"): 1.0,
    ("psia", "psi"): 1.0,
    ("psi", "psia"): 1.0,
    ("bar", "psi"): 14.5037738,
    ("psi", "bar"): 1 / 14.5037738,
    ("kpa", "psi"): 0.145037738,
    ("psi", "kpa"): 1 / 0.145037738,
    ("stb/d", "m3/d"): 0.158987295,
    ("m3/d", "stb/d"): 1 / 0.158987295,
    ("mmscf/d", "scf/d"): 1_000_000.0,
    ("scf/d", "mmscf/d"): 1 / 1_000_000.0,
    ("mmscf/d", "sm3/d"): 28316.846592,
    ("sm3/d", "mmscf/d"): 1 / 28316.846592,
    ("ft", "m"): 0.3048,
    ("m", "ft"): 1 / 0.3048,
}


class SimpleUnitConverter:
    """Pure-Python fallback covering common oilfield units. See module docstring."""

    def convert(self, from_unit: str, to_unit: str, value: float) -> float:
        if value is None:
            return value
        fu, tu = (from_unit or "").strip().lower(), (to_unit or "").strip().lower()
        if not fu or not tu or fu == tu:
            return value
        if fu in ("%", "percent") and tu in ("%", "percent"):
            return value
        if fu == "degf" and tu == "degc":
            return (value - 32) * 5 / 9
        if fu == "degc" and tu == "degf":
            return value * 9 / 5 + 32
        factor = _LINEAR_FACTORS.get((fu, tu))
        if factor is not None:
            return value * factor
        raise UnitConversionError(f"No conversion known from {from_unit!r} to {to_unit!r}")


_default_converter: UnitConverter = SimpleUnitConverter()


def set_default_converter(converter: UnitConverter) -> None:
    global _default_converter
    _default_converter = converter


def ipt_unit_conv(from_unit: str, to_unit: str, value: float) -> float:
    """Module-level function mirroring the VBA global `iPT_UnitConv(InputUnit, OutputUnit, TheValue)`."""
    return _default_converter.convert(from_unit, to_unit, value)
