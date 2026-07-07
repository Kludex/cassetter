from __future__ import annotations

from typing import TypedDict

from cassetter.cassette import BeforeRecordRequest, BeforeRecordResponse, UriNormalizer


class CassetteConfig(TypedDict, total=False):
    """Configuration for a cassette recording/playback session."""

    record_mode: str
    match_on: list[str]
    ignore_json_paths: list[str]
    filter_headers: list[str]
    filter_query_parameters: list[str]
    body_scrub_patterns: list[str]
    filter_replacement: str
    cassette_dir: str
    intercept: list[str]
    max_age: str
    on_expiry: str
    ignore_localhost: bool
    ignore_hosts: list[str]
    before_record_request: BeforeRecordRequest
    before_record_response: BeforeRecordResponse
    uri_normalizer: UriNormalizer
