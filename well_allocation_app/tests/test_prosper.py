import sys
import types
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.prosper import ProsperError, ProsperSession  # noqa: E402


class FakeOpenServer:
    """Behaves like the openserver package: raises ValueError and disconnects on any error."""

    rejected = {"PROSPER.START()", "PROSPER.ANL.GRD.CALC()"}

    def __init__(self):
        self.status = "Disconnected"
        self.cmds, self.values = [], {}

    def connect(self):
        self.status = "Connected"

    def disconnect(self):
        self.status = "Disconnected"

    def _need(self):
        if self.status != "Connected":
            raise RuntimeError("used while disconnected")

    def DoCmd(self, cmd):
        self._need()
        self.cmds.append(cmd)
        if cmd in self.rejected:
            self.disconnect()
            raise ValueError("Command not recognised")

    def DoSet(self, tag, val):
        self._need()
        self.values[tag] = val

    def DoGet(self, tag):
        self._need()
        if tag != "PROSPER.OUT.GRD.RES[0][0][57].Pres":
            self.disconnect()
            raise ValueError("Variable not found")
        return str(self.values["PROSPER.ANL.GRD.Pres"] + 2000)


@pytest.fixture
def fake(monkeypatch, tmp_path):
    mod = types.ModuleType("openserver")
    mod.OpenServer = FakeOpenServer
    monkeypatch.setitem(sys.modules, "openserver", mod)
    f = tmp_path / "J03-P.Out"
    f.write_text("")
    return f


def test_tolerates_start_and_falls_back_to_calc_without_parens(fake):
    s = ProsperSession(f'"{fake}"')
    assert s.gradient(1200, 5000, 20, 1100, "PROSPER.OUT.GRD.RES[0][0][57].Pres") == 3200
    assert s.gradient(1300, 5000, 20, 1100, "PROSPER.OUT.GRD.RES[0][0][57].Pres") == 3300
    assert s._calc == "PROSPER.ANL.GRD.CALC"
    assert s._c.cmds.count("PROSPER.ANL.GRD.CALC()") == 1  # tried once, then remembered


def test_errors_name_the_failing_string(fake):
    s = ProsperSession(str(fake))
    with pytest.raises(ProsperError, match=r"PROSPER.OUT.VLP.RES\[0\]\[19\].PRES"):
        s.gradient(1200, 5000, 20, 1100, "PROSPER.OUT.VLP.RES[0][19].PRES")


def test_missing_file_is_reported(fake):
    with pytest.raises(ProsperError, match="not found"):
        ProsperSession("P:/nowhere/J03-P.Out")
