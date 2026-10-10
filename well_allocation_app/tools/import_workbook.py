"""Import the well configuration from an Allocation.xlsm into config/wells.csv.

    python tools/import_workbook.py path/to/Allocation.xlsm
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.config import save_wells, wells_from_workbook  # noqa: E402

if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    df = wells_from_workbook(sys.argv[1])
    save_wells(df)
    print(f"Imported {len(df)} wells -> config/wells.csv")
