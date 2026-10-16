"""Make nested results JSON-safe (numpy scalars/arrays, NaN)."""
from __future__ import annotations

import math
from typing import Any

import numpy as np


def to_jsonable(x: Any) -> Any:
    if isinstance(x, dict):
        return {str(k): to_jsonable(v) for k, v in x.items()}
    if isinstance(x, (list, tuple, set)):
        return [to_jsonable(v) for v in x]
    if isinstance(x, np.ndarray):
        return to_jsonable(x.tolist())
    if isinstance(x, np.generic):
        return to_jsonable(x.item())
    if isinstance(x, float):
        return None if (math.isnan(x) or math.isinf(x)) else x
    return x
