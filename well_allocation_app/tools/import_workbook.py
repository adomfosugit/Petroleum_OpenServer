"""Load the well list into config/wells.csv from the Configuration Sheet (CSV) or the Allocation workbook.

    python tools/import_workbook.py path/to/ConfigurationSheet.csv
    python tools/import_workbook.py path/to/Allocation.xlsm
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.config import read_wells_csv, save_wells, wells_from_workbook  # noqa: E402

if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    src = sys.argv[1]
    df = read_wells_csv(src) if src.lower().endswith(".csv") else wells_from_workbook(src)
    save_wells(df)
    print(f"Imported {len(df)} wells -> config/wells.csv")
