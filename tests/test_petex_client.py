import pytest

from petroleum_openserver.petex_client import PetexClient


class FakeCom:
    """Minimal stand-in for the win32com Dispatch object `PetexClient.server` wraps."""

    def __init__(self):
        self.values: dict[str, object] = {}
        self.errors: dict[str, int] = {}

    def GetValue(self, tag):
        if tag not in self.values:
            raise RuntimeError(f"not found: {tag}")
        return self.values[tag]

    def GetLastError(self, app):
        return self.errors.get(app, 0)

    def SetValue(self, tag, value):
        self.values[tag] = value
        return 0


@pytest.fixture
def client():
    c = PetexClient()
    c.status = "Connected"
    c.server = FakeCom()
    return c


def test_check_os_string_true_when_value_resolves(client):
    client.server.values["GAP.MOD[0].SEP[{X}].Label"] = "X"
    assert client.check_os_string("GAP.MOD[0].SEP[{X}].Label") is True


def test_check_os_string_false_when_missing(client):
    assert client.check_os_string("GAP.MOD[0].SEP[{MISSING}].Label") is False


def test_check_os_string_false_on_openserver_error(client):
    client.server.values["GAP.FOO"] = 1
    client.server.errors["GAP"] = 5
    assert client.check_os_string("GAP.FOO") is False


def test_do_set_no_err_swallows_failures(client):
    assert client.do_set_no_err("GAP.MOD[0].SEP[{X}].Pres", 100) is True
    assert client.server.values["GAP.MOD[0].SEP[{X}].Pres"] == 100


def test_do_gap_func_fast_returns_none_on_error(client):
    assert client.do_gap_func_fast("GAP.NOT.THERE") is None


def test_open_file_returns_false_when_path_missing(client):
    assert client.open_file("", "GAP") is False
    assert client.open_file("/no/such/file.gap", "GAP") is False


def test_open_file_starts_and_opens(tmp_path, client, monkeypatch):
    model = tmp_path / "model.gap"
    model.write_text("dummy")

    calls = []
    monkeypatch.setattr(client, "DoCmd", lambda cmd: calls.append(cmd))

    assert client.open_file(str(model), "GAP") is True
    assert calls[0] == "GAP.START()"
    assert calls[1] == f'GAP.OPENFILE("{model}")'
