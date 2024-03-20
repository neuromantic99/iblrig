from pathlib import Path
import sys


def path_helper() -> None:
    parent = Path(__file__).parent.parent
    sys.path.append(str(parent))
