from __future__ import annotations

from collections.abc import Callable
from typing import Any

from nntpintel.candidates import qualify_candidates
from nntpintel.discovery import refresh_builtin_source
from nntpintel.probe import ProbeObservation, probe
from nntpintel.storage import Storage


def run_candidate_cycle(
    storage: Storage,
    source: str,
    *,
    limit: int = 3,
    timeout: float = 5.0,
    content: str | None = None,
    probe_func: Callable[..., ProbeObservation] = probe,
    refresh_func: Callable[..., dict[str, int]] = refresh_builtin_source,
) -> dict[str, Any]:
    if limit < 0:
        raise ValueError("limit must be zero or greater")
    if limit > 10:
        raise ValueError("conservative candidate cycle limit cannot exceed 10")
    if timeout <= 0 or timeout > 15:
        raise ValueError("candidate cycle timeout must be greater than 0 and at most 15 seconds")

    refresh = refresh_func(storage, source, activate=False, content=content)
    qualifications = qualify_candidates(
        storage,
        limit=limit,
        timeout=timeout,
        probe_func=probe_func,
    )
    return {
        "source": source,
        "refresh": refresh,
        "qualification_count": len(qualifications),
        "qualifications": qualifications,
        "promotion_count": 0,
    }
