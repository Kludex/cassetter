from __future__ import annotations

import warnings
from collections.abc import Mapping
from typing import Any

import pytest

from cassetter.cassette import Cassette

ON_UNPLAYED_ACTIONS = ("ignore", "warn", "fail")

_REPORTS = pytest.StashKey[dict[str, pytest.TestReport]]()


class UnplayedInteractionsWarning(UserWarning):
    """A passing test left recorded interactions unplayed."""


def add_options(parser: pytest.Parser) -> None:
    """Add the `vcr_on_unplayed` ini option."""
    parser.addini(
        "vcr_on_unplayed",
        "Action when a passing test leaves recorded interactions unplayed: ignore, warn, or fail.",
        default=None,
    )


def store_report(item: pytest.Item, report: pytest.TestReport) -> None:
    """Keep each phase's report so the cassette fixture can see how the test went."""
    item.stash.setdefault(_REPORTS, {})[report.when] = report


def resolve_on_unplayed(
    marker_kwargs: Mapping[str, Any], vcr_config: Mapping[str, Any] | None, ini_on_unplayed: str | None
) -> str:
    """The `on_unplayed` action for a test: marker, then `vcr_config`, then the ini option."""
    action = marker_kwargs.get("on_unplayed") or (vcr_config or {}).get("on_unplayed") or ini_on_unplayed or "ignore"
    if action not in ON_UNPLAYED_ACTIONS:
        raise ValueError(f"invalid on_unplayed: {action!r} (expected 'ignore', 'warn', or 'fail')")
    return action


def unplayed_interactions(cassette: Cassette) -> dict[str, list[int]]:
    """Indexes of the interactions nothing replayed, per protocol."""
    unplayed = {
        "HTTP": cassette.played_indices,
        "gRPC": cassette.grpc_played_indices,
        "WebSocket": cassette.ws_played_indices,
    }
    return {
        protocol: [index for index, played in enumerate(indices) if not played]
        for protocol, indices in unplayed.items()
        if not all(indices)
    }


def check_unplayed(item: pytest.Item, cassette: Cassette, action: str) -> None:
    """Warn or fail when a passing replay-only test left recorded interactions unplayed.

    A test that failed or was skipped already reports why, and a cassette that
    can record is still being written, so neither is checked.
    """
    if action == "ignore" or cassette.can_record:
        return
    if any(report.failed or report.skipped for report in item.stash.get(_REPORTS, {}).values()):
        return
    if not (unplayed := unplayed_interactions(cassette)):
        return
    details = "; ".join(f"{protocol} {indexes}" for protocol, indexes in unplayed.items())
    message = f"cassette {cassette.path} left interactions unplayed: {details}"
    if action == "fail":
        pytest.fail(message, pytrace=False)
    warnings.warn(message, UnplayedInteractionsWarning, stacklevel=1)
