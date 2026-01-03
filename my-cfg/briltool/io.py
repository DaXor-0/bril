from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, Optional


def load_json(input_file: Optional[Path]) -> Any:
    """
    Loads JSON content from a file or stdin if input_file is None or '-'.
    """
    if input_file is None or str(input_file) == "-":
        return json.load(sys.stdin)

    with input_file.open("r", encoding="utf-8") as f:
        return json.load(f)

