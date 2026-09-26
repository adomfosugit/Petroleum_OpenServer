from __future__ import annotations

import pytest


class FakeClient:
    """Stand-in for `PetexClient` that never touches COM/OpenServer, so the
    pure orchestration logic in `vlp.py`/`ipr_matching.py`/`gap_validation.py`
    can be exercised without Windows or a running PROSPER/GAP instance.
    """

    def __init__(self, get_values: dict | None = None):
        self.get_values = dict(get_values or {})
        self.set_calls: list[tuple[str, object]] = []
        self.cmds: list[str] = []
        self.status = "Connected"

    def DoSet(self, tag, value=""):
        self.set_calls.append((tag, value))

    def DoGet(self, tag):
        return self.get_values.get(tag, 0)

    def DoCmd(self, cmd):
        self.cmds.append(cmd)

    def do_slow_cmd(self, cmd):
        self.cmds.append(cmd)

    def do_set_no_err(self, tag, value=""):
        self.set_calls.append((tag, value))
        return True

    def do_gap_func_fast(self, tag):
        return self.get_values.get(tag)

    def check_os_string(self, tag):
        return tag in self.get_values

    def open_file(self, path, app):
        return True


@pytest.fixture
def fake_client() -> FakeClient:
    return FakeClient()
