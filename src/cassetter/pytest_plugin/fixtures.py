from __future__ import annotations

import os
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from cassetter._core import MatchConfig, SecurityConfig
from cassetter._types import CassetteConfig
from cassetter.cassette import Cassette
from cassetter.context import resolve_interceptors
from cassetter.intercept._base import InterceptorProtocol
from cassetter.recording import RecordMode


@pytest.fixture(scope="module")
def vcr_config() -> CassetteConfig:
    """Override this fixture to provide default VCR configuration."""
    return CassetteConfig()


def _resolve_cassette(
    node_name: str,
    marker_args: tuple[Any, ...],
    marker_kwargs: dict[str, Any],
    vcr_config: CassetteConfig,
    cli_record_mode: str | None,
    test_fspath: str,
) -> tuple[Cassette, list[InterceptorProtocol]]:
    """Resolve cassette configuration and create a Cassette instance."""
    cassette_name = node_name + ".yaml"
    cassette_dir = vcr_config.get("cassette_dir", "cassettes")
    record_mode_str = vcr_config.get("record_mode", "none")

    # Marker can override
    if marker_args:
        cassette_name = marker_args[0]
    if "record_mode" in marker_kwargs:
        record_mode_str = marker_kwargs["record_mode"]
    if "cassette_dir" in marker_kwargs:
        cassette_dir = marker_kwargs["cassette_dir"]

    # CLI override
    if cli_record_mode is not None:
        record_mode_str = cli_record_mode

    record_mode = RecordMode.from_str(record_mode_str)

    # Resolve cassette path: {test_dir}/cassettes/{test_file_stem}/{cassette_name}
    test_file = Path(test_fspath)
    test_dir = str(test_file.parent)
    test_file_stem = test_file.stem
    cassette_path = os.path.join(test_dir, cassette_dir, test_file_stem, cassette_name)

    match_config = MatchConfig(
        match_on=vcr_config.get("match_on"),
        ignore_json_paths=vcr_config.get("ignore_json_paths"),
    )

    security_kwargs: dict[str, Any] = {}
    if "filtered_headers" in vcr_config:
        security_kwargs["filtered_headers"] = vcr_config["filtered_headers"]
    if "filtered_query_params" in vcr_config:
        security_kwargs["filtered_query_params"] = vcr_config["filtered_query_params"]
    if "body_scrub_patterns" in vcr_config:
        security_kwargs["body_scrub_patterns"] = vcr_config["body_scrub_patterns"]
    if "filter_replacement" in vcr_config:
        security_kwargs["replacement"] = vcr_config["filter_replacement"]
    security_config = SecurityConfig(**security_kwargs)

    max_age = marker_kwargs.get("max_age", vcr_config.get("max_age"))
    on_expiry = marker_kwargs.get("on_expiry", vcr_config.get("on_expiry", "warn"))

    ignore_localhost = vcr_config.get("ignore_localhost", False)
    ignore_hosts = vcr_config.get("ignore_hosts")
    before_record_request = vcr_config.get("before_record_request")

    cassette = Cassette(
        cassette_path,
        record_mode=record_mode,
        match_config=match_config,
        security_config=security_config,
        max_age=max_age,
        on_expiry=on_expiry,
        ignore_localhost=ignore_localhost,
        ignore_hosts=ignore_hosts,
        before_record_request=before_record_request,
    )
    cassette.load()

    intercept_names = vcr_config.get("intercept")
    interceptors = resolve_interceptors(intercept_names)
    return cassette, interceptors


@pytest.fixture(autouse=True)
def vcr_cassette(request: pytest.FixtureRequest, vcr_config: CassetteConfig) -> Iterator[Cassette | None]:
    """Activates cassette recording/replay for tests marked with @pytest.mark.vcr."""
    marker = request.node.get_closest_marker("vcr")
    if marker is None:
        yield None
        return

    cli_record_mode = request.config.getoption("--record-mode", default=None)

    cassette, interceptors = _resolve_cassette(
        node_name=request.node.name,
        marker_args=marker.args,
        marker_kwargs=dict(marker.kwargs),
        vcr_config=vcr_config,
        cli_record_mode=cli_record_mode,
        test_fspath=str(request.path),
    )

    # Track loaded cassette paths for orphan detection
    _loaded_cassettes = getattr(request.config, "_vcr_loaded_cassettes", None)
    if _loaded_cassettes is not None:
        _loaded_cassettes.add(os.path.abspath(cassette.path))

    for interceptor in interceptors:
        interceptor.install(cassette)

    yield cassette

    # Uninstall interceptors and save
    for interceptor in reversed(interceptors):
        interceptor.uninstall()
    cassette.save()
