"""PROSPER access through Petex OpenServer, plus a stand-in model for demo mode.

Live mode tries, in order:
  1. the `openserver` Python package (from openserver import OpenServer)
  2. the raw COM object "PX32.OpenServer.1" through pywin32, which is what the
     VBA macros create.
Both expose the same three calls the macros use: DoCmd, DoSet, DoGet.
"""
from __future__ import annotations

import hashlib
import math
import os


class ProsperError(RuntimeError):
    pass


def _app_name(tag: str) -> str:
    return tag.split(".", 1)[0].upper()


class _ComServer:
    """Thin wrapper over PX32.OpenServer.1 mirroring Module1's DoCmd/DoSet/DoGet."""

    def __init__(self):
        try:
            import pythoncom
            pythoncom.CoInitialize()
        except Exception:
            pass
        import win32com.client
        self._s = win32com.client.Dispatch("PX32.OpenServer.1")

    def connect(self):
        pass

    def DoCmd(self, cmd: str):
        err = self._s.DoCommand(cmd)
        if err > 0:
            raise ProsperError(self._s.GetErrorDescription(err))

    def DoSet(self, tag: str, value):
        self._s.SetValue(tag, value)
        err = self._s.GetLastError(_app_name(tag))
        if err > 0:
            raise ProsperError(self._s.GetErrorDescription(err))

    def DoGet(self, tag: str):
        val = self._s.GetValue(tag)
        err = self._s.GetLastError(_app_name(tag))
        if err > 0:
            raise ProsperError(self._s.GetErrorDescription(err))
        return val

    def disconnect(self):
        self._s = None


def openserver_available() -> tuple[bool, str]:
    try:
        import openserver  # noqa: F401
        return True, "openserver package"
    except Exception:
        pass
    try:
        import win32com.client  # noqa: F401
        return True, "PX32.OpenServer.1 via pywin32"
    except Exception:
        return False, "Neither the openserver package nor pywin32 is installed"


class ProsperSession:
    """One PROSPER file opened for a batch of gradient calculations."""

    kind = "live"

    # The VBA macros send "PROSPER.ANL.GRD.CALC"; the Python sample sends "...CALC()".
    # Both are tried, and whichever PROSPER accepts is reused for the rest of the run.
    CALC_FORMS = ["PROSPER.ANL.GRD.CALC()", "PROSPER.ANL.GRD.CALC"]

    def __init__(self, prosper_file: str, show: bool = False):
        try:
            from openserver import OpenServer
            self._c = OpenServer()
        except ImportError:
            self._c = _ComServer()
        self._c.connect()
        self._calc = None
        # The openserver package raises (and disconnects) when PROSPER is already
        # running, so a failed START is expected and ignored, as in petex_client.open_file.
        try:
            self._c.DoCmd("PROSPER.START()")
        except Exception:
            self._reconnect()
        path = prosper_file.strip().strip('"')
        if not os.path.exists(path):
            raise ProsperError(f"PROSPER file not found from this computer: {path}")
        self._cmd(f'PROSPER.OPENFILE("{path}")')
        if show:
            try:
                self._c.DoCmd("PROSPER.SCREEN.SHOW")
            except Exception:
                self._reconnect()

    def _reconnect(self):
        if getattr(self._c, "status", "Connected") != "Connected":
            self._c.connect()

    def _cmd(self, cmd: str):
        try:
            self._c.DoCmd(cmd)
        except Exception as exc:
            self._reconnect()
            raise ProsperError(f"PROSPER rejected the command {cmd}: {exc}") from exc

    def _set(self, tag: str, value: float):
        try:
            self._c.DoSet(tag, value)
        except Exception as exc:
            self._reconnect()
            raise ProsperError(f"PROSPER could not set {tag} = {value}: {exc}") from exc

    def _get(self, tag: str):
        try:
            return self._c.DoGet(tag)
        except Exception as exc:
            self._reconnect()
            raise ProsperError(f"PROSPER could not read {tag} (check the well's result string): {exc}") from exc

    def _run_calc(self):
        if self._calc:
            return self._cmd(self._calc)
        errors = []
        for form in self.CALC_FORMS:
            try:
                self._c.DoCmd(form)
                self._calc = form
                return
            except Exception as exc:
                self._reconnect()
                errors.append(f"{form}: {exc}")
        raise ProsperError("PROSPER rejected the gradient calculation. " + "; ".join(errors))

    def gradient(self, thp: float, rate: float, wct: float, gor: float, result_string: str) -> float:
        """PROSPER.ANL.GRD: set top-node pressure, WC, rate, GOR; calculate; read the result string."""
        self._set("PROSPER.ANL.GRD.Pres", float(thp))
        self._set("PROSPER.ANL.GRD.WC", float(wct))
        self._set("PROSPER.ANL.GRD.Rate", float(rate))
        self._set("PROSPER.ANL.GRD.GOR", float(gor))
        self._run_calc()
        val = self._get(result_string)
        try:
            return float(val)
        except (TypeError, ValueError) as exc:
            raise ProsperError(f"PROSPER returned a non-numeric value for {result_string}: {val!r}") from exc

    def close(self):
        try:
            self._c.disconnect()
        except Exception:
            pass

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()


class DemoProsper:
    """A smooth stand-in for a PROSPER gradient so the app runs without Petex.

    BHP = THP + hydrostatic head (lightened by gas) + friction growing with rate.
    Each well gets its own depth so wells behave differently.
    """

    kind = "demo"

    def __init__(self, prosper_file: str = "", show: bool = False, well: str = ""):
        h = int(hashlib.md5((well or prosper_file).encode()).hexdigest(), 16)
        self.depth_ft = 7200 + (h % 21) * 80

    def gradient(self, thp, rate, wct, gor, result_string=""):
        return demo_bhp(self.depth_ft, thp, rate, wct, gor)

    def close(self):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()


def demo_bhp(depth_ft, thp, rate, wct, gor) -> float:
    w = min(max(wct, 0.0), 100.0) / 100.0
    rate = max(rate, 0.0)
    glr = max(gor, 0.0) * (1 - w)
    lift = glr / (glr + 900.0)
    liquid_grad = 0.433 * (0.84 * (1 - w) + 1.03 * w)
    hydro = depth_ft * liquid_grad * (1 - 0.55 * lift)
    friction = 1.2e-5 * rate ** 1.8 * (1 + 0.3 * lift)
    return float(thp + hydro + friction)


def close_prosper() -> str:
    """Close PROSPER, and the file it has open, from the program.

    Sends PROSPER.SHUTDOWN through OpenServer (the same connection the gradient runs use), then
    disconnects. Nothing is saved: the app never changes the model file, it only sets the gradient
    inputs, so there is nothing to keep. Raises ProsperError if PROSPER could not be reached.
    """
    c = None
    try:
        try:
            from openserver import OpenServer
            c = OpenServer()
        except ImportError:
            c = _ComServer()
        c.connect()
        c.DoCmd("PROSPER.SHUTDOWN")
    except Exception as exc:
        raise ProsperError(f"Could not close PROSPER (is it running?): {exc}") from exc
    finally:
        try:
            if c is not None:
                c.disconnect()
        except Exception:
            pass
    return "PROSPER closed"


def open_session(mode: str, well_row, show: bool = False):
    if mode == "live":
        if not well_row.get("prosper_file"):
            raise ProsperError(f"No PROSPER file configured for {well_row['well']}.")
        return ProsperSession(well_row["prosper_file"], show=show)
    return DemoProsper(well=well_row["well"])


def is_finite(*vals) -> bool:
    return all(v is not None and isinstance(v, (int, float)) and math.isfinite(v) for v in vals)
