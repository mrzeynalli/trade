"""Canonical request keys.

A canonical key is a stable SHA-256 over the endpoint plus the normalised
parameter set. Two logically identical requests always produce the same key,
which is what makes both the raw-response cache and job de-duplication work.
"""

from __future__ import annotations

import hashlib
from typing import Any, Mapping

# Parameters whose value is a comma-separated list are sorted so that
# "2020,2019" and "2019,2020" collapse to one key.
LIST_PARAMS = {
    "period", "reporterCode", "partnerCode", "partner2Code",
    "cmdCode", "flowCode", "customsCode", "motCode",
}


def normalise_params(params: Mapping[str, Any]) -> dict[str, str]:
    out: dict[str, str] = {}
    for raw_key, raw_value in params.items():
        if raw_value is None or raw_value == "":
            continue
        value = ",".join(str(v) for v in raw_value) if isinstance(raw_value, (list, tuple, set)) else str(raw_value)
        if raw_key in LIST_PARAMS and "," in value:
            value = ",".join(sorted(part.strip() for part in value.split(",") if part.strip()))
        out[raw_key] = value
    return dict(sorted(out.items()))


def canonical_key(endpoint: str, params: Mapping[str, Any]) -> str:
    normalised = normalise_params(params)
    blob = endpoint.strip("/") + "?" + "&".join(f"{k}={v}" for k, v in normalised.items())
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def canonical_string(endpoint: str, params: Mapping[str, Any]) -> str:
    normalised = normalise_params(params)
    return endpoint.strip("/") + "?" + "&".join(f"{k}={v}" for k, v in normalised.items())
