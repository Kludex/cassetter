from __future__ import annotations

import os
from contextlib import AbstractContextManager

from cassetter.cassette import BeforeRecordRequest, BeforeRecordResponse, Cassette
from cassetter.config import Cassetter
from cassetter.recording import RecordMode


def use_cassette(
    path: str | os.PathLike[str],
    *,
    record_mode: RecordMode | str = RecordMode.ONCE,
    match_on: list[str] | None = None,
    ignore_json_paths: list[str] | None = None,
    filter_headers: list[str] | None = None,
    filter_query_parameters: list[str] | None = None,
    body_scrub_patterns: list[str] | None = None,
    filter_replacement: str | None = None,
    intercept: list[str] | None = None,
    max_age: str | None = None,
    on_expiry: str = "warn",
    ignore_localhost: bool = False,
    ignore_hosts: list[str] | None = None,
    before_record_request: BeforeRecordRequest | None = None,
    before_record_response: BeforeRecordResponse | None = None,
) -> AbstractContextManager[Cassette]:
    """Context manager for recording/replaying HTTP interactions.

    Args:
        path: Path to the cassette YAML file.
        record_mode: Controls recording behavior.
        match_on: Fields to match on (default: ["method", "uri"]).
        ignore_json_paths: JSON paths to ignore during matching.
        filter_headers: Headers to filter from cassettes.
        filter_query_parameters: Query params to filter.
        body_scrub_patterns: Body patterns to scrub.
        filter_replacement: Replacement string for filtered values.
        intercept: HTTP libraries to intercept (default: auto-detect).
        max_age: Maximum cassette age before it is considered expired, e.g. "30d".
        on_expiry: What to do with an expired cassette: "warn", "fail", or "rerecord".
        ignore_localhost: Bypass the cassette for requests to localhost.
        ignore_hosts: Bypass the cassette for requests to matching hosts.
        before_record_request: Hook to modify or skip requests.
        before_record_response: Hook to modify or skip responses.

    Returns:
        A context manager yielding the active cassette.
    """
    config = Cassetter(
        record_mode=record_mode,
        match_on=match_on,
        ignore_json_paths=ignore_json_paths,
        filter_headers=filter_headers,
        filter_query_parameters=filter_query_parameters,
        body_scrub_patterns=body_scrub_patterns,
        filter_replacement=filter_replacement,
        intercept=intercept,
        max_age=max_age,
        on_expiry=on_expiry,
        ignore_localhost=ignore_localhost,
        ignore_hosts=ignore_hosts,
        before_record_request=before_record_request,
        before_record_response=before_record_response,
    )
    return config.use_cassette(path)
