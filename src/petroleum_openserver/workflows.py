"""High-level entry points tying the ported modules together - the Python
analogues of the top-level VBA Subs a user would run from the Excel ribbon
(`GetData_All`, `RunGAPValidation`, `VLPCalc_All`, `MatchIPR`,
`RunGAP_WellValidation_All`).

`ShowSummary`/`ShowDetails` (hide/show Excel columns) have no equivalent here
and aren't ported - they were a pure Excel-UI convenience.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import openpyxl
from openpyxl.workbook.workbook import Workbook
from openpyxl.worksheet.worksheet import Worksheet

from .data_import import get_data_all
from .gap_validation import run_gap_validation, run_gap_well_validation_all
from .ipr_matching import match_ipr
from .petex_client import PetexClient
from .vlp import vlp_calc_all


def open_workbook(path: str) -> Workbook:
    return openpyxl.load_workbook(path)


@dataclass
class Workflow:
    """Bundles the OpenServer client + worksheets used by every top-level
    entry point, so a driving script doesn't have to keep threading them
    through by hand.
    """

    client: PetexClient
    config_ws: Worksheet
    validation_ws: Worksheet
    pi_server: Optional[str] = None

    @classmethod
    def from_workbook(
        cls,
        client: PetexClient,
        workbook: Workbook,
        validation_sheet: str,
        config_sheet: str = "Configuration",
        pi_server: Optional[str] = None,
    ) -> "Workflow":
        return cls(client, workbook[config_sheet], workbook[validation_sheet], pi_server)

    def get_data(self) -> None:
        """Port of `GetData_All` (pull Configuration/OFM/PI data onto the validation sheet)."""
        get_data_all(self.config_ws, self.validation_ws, self.pi_server)

    def run_gap_validation(self) -> None:
        """Port of `RunGAPValidation` (network-wide GAP solve)."""
        run_gap_validation(self.client, self.config_ws, self.validation_ws)

    def vlp_calc_all(self) -> None:
        """Port of `VLPCalc_All` (per-well PROSPER VLP calculations)."""
        vlp_calc_all(self.client, self.config_ws, self.validation_ws)

    def match_ipr(self) -> None:
        """Port of `MatchIPR` (re-estimate zonal reservoir pressures)."""
        match_ipr(self.config_ws, self.validation_ws)

    def run_gap_well_validation_all(self) -> None:
        """Port of `RunGAP_WellValidation_All` (isolated per-well GAP checks)."""
        run_gap_well_validation_all(self.client, self.config_ws, self.validation_ws)
