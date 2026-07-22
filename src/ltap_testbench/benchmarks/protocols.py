from __future__ import annotations

import json
from enum import Enum
from hashlib import sha256
from math import isfinite
from typing import Any

NON_MEASUREMENT_FIELDS = {
    "experiment_name",
    "firmware_version",
    "modem_under_comparison",
    "notes",
    "run_id",
    "timestamp",
    "variant_label",
}


def _canonical_value(value: Any) -> Any:
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, float):
        if not isfinite(value):
            raise ValueError("protocol definitions cannot contain NaN or infinity")
        return value
    if isinstance(value, dict):
        return {
            str(key): _canonical_value(item)
            for key, item in sorted(value.items(), key=lambda entry: str(entry[0]))
            if str(key) not in NON_MEASUREMENT_FIELDS
        }
    if isinstance(value, list | tuple):
        return [_canonical_value(item) for item in value]
    return value


def canonical_protocol_json(definition: dict[str, Any]) -> str:
    return json.dumps(
        _canonical_value(definition),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )


def protocol_hash(definition: dict[str, Any]) -> str:
    return sha256(canonical_protocol_json(definition).encode("utf-8")).hexdigest()
