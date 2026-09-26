"""Python port of the Jubilee GAP/PROSPER validation, VLP calculation and IPR
matching VBA macros, built on Petroleum Experts' `openserver` OpenServer client.

See README.md for architecture notes and the assumptions made where the
original VBA relied on code that wasn't part of what was ported (`getResPres`,
`iPT_UnitConv`'s exact COM method, `PIValue`).
"""

from .exceptions import ProgramTerminated
from .petex_client import PetexClient, terminate
from .workflows import Workflow, open_workbook

__all__ = [
    "PetexClient",
    "ProgramTerminated",
    "Workflow",
    "open_workbook",
    "terminate",
]

__version__ = "0.1.0"
