"""Thin extension of the `openserver` package's `OpenServer` client.

`openserver.OpenServer.DoCmd` / `DoSet` / `DoGet` raise `ValueError` *and
disconnect the session* on any OpenServer error (see the pip package's
source: it calls `self.disconnect()` in the `except` block before
re-raising). That mirrors the VBA `DoCmd`/`DoSet`/`DoGet` helpers, which
popped a MsgBox on error.

But several of the original macros deliberately probe for something that
may legitimately not exist yet (`CheckOsString`, masked/optional
`DoSetNoErr` calls, `DoGAPFuncFast` used in a search loop). Doing that
through the disconnect-on-error path would tear down the OpenServer
session (and release the IPM licence) on every "not found" case, so those
three need to talk to the raw COM object directly and swallow errors
instead of raising.

`PetexClient` adds those, plus `open_file` (the `fOSOpenFile` port) and
`do_slow_cmd` (kept only for readability/parity with the VBA source: the
pip package's `DoCmd` already makes a blocking COM call, so there is no
Excel-UI-thread reason to poll `IsBusy` the way the original VBA did).
"""

from __future__ import annotations

import os
from typing import Any, Optional

from openserver import OpenServer
from openserver.openserver import _format_os_value, _parse_os_value

from .exceptions import ProgramTerminated


class PetexClient(OpenServer):
    """OpenServer client used throughout this package instead of raw `openserver.OpenServer`."""

    def do_slow_cmd(self, cmd: str) -> None:
        """Port of the VBA `DoSlowCmd` sub (e.g. `PROSPER.ANL.VLP.CALC`, `GAP.SOLVENETWORK(0)`).

        A plain `DoCmd` is enough here: the COM call already blocks until the
        calculation finishes.
        """
        self.DoCmd(cmd)

    def check_os_string(self, tag: str) -> bool:
        """Port of the VBA `CheckOsString` function.

        Returns True if `tag` currently resolves to a valid OpenServer item,
        without raising or disconnecting when it doesn't (unlike `DoGet`).
        """
        if self.status != "Connected":
            self.connect()
        try:
            self.server.GetValue(tag)
            app_name = self.GetAppName(tag)
            err = self.server.GetLastError(app_name)
            return err == 0
        except Exception:
            return False

    def do_set_no_err(self, tag: str, value: Any = "") -> bool:
        """Port of the VBA `DoSetNoErr` sub: best-effort set, no raise/disconnect on failure."""
        if self.status != "Connected":
            self.connect()
        try:
            self.server.SetValue(tag, _format_os_value(value))
            app_name = self.GetAppName(tag)
            err = self.server.GetLastError(app_name)
            return err == 0
        except Exception:
            return False

    def do_gap_func_fast(self, tag: str) -> Optional[Any]:
        """Port of the VBA `DoGAPFuncFast` function (used e.g. inside `ISCONNECTEDTO(...)` probes).

        Returns the parsed value, or None if the call errored - callers in the
        original VBA only ever compared the result to a literal (e.g. `= 1`),
        so None simply never matches.
        """
        if self.status != "Connected":
            self.connect()
        try:
            value = self.server.GetValue(tag)
            app_name = self.GetAppName(tag)
            err = self.server.GetLastError(app_name)
            if err:
                return None
            return _parse_os_value(value, tag)
        except Exception:
            return None

    def open_file(self, file_path: str, app: str) -> bool:
        """Port of the VBA `fOSOpenFile(FileName, App)` function.

        `app` is the OpenServer module name, e.g. "GAP" or "PROSPER".
        Starts the application if needed, then opens `file_path`. Returns
        False (instead of the VBA pattern of calling `TerminateProgram`)
        so the caller decides how to react.
        """
        app = app.upper().strip()
        if not file_path:
            return False
        if not os.path.exists(file_path):
            return False
        try:
            self.DoCmd(f"{app}.START()")
        except ValueError:
            # Already running is not fatal - DoCmd already disconnected the
            # session on the error, but it self-heals (reconnects) on the
            # next call below.
            pass
        try:
            escaped = file_path.replace('"', '""')
            self.DoCmd(f'{app}.OPENFILE("{escaped}")')
        except ValueError:
            return False
        return True


def terminate(message: str = "Program Terminated") -> None:
    """Port of the VBA `TerminateProgram` sub."""
    raise ProgramTerminated(message)
