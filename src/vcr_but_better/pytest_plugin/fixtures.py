from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import pytest

from vcr_but_better._core import MatchConfig, SecurityConfig
from vcr_but_better._types import CassetteConfig
from vcr_but_better.cassette import Cassette
from vcr_but_better.recording import RecordMode


@pytest.fixture(scope="module")
def vcr_config() -> CassetteConfig:
    """Override this fixture to provide default VCR configuration."""
    return CassetteConfig()


@pytest.fixture
def vcr_cassette(request: pytest.FixtureRequest, vcr_config: CassetteConfig) -> Cassette:
    """Provides a Cassette for the current test based on marker or config."""
    marker = request.node.get_closest_marker("vcr")

    cassette_name = request.node.name + ".yaml"
    cassette_dir = vcr_config.get("cassette_dir", "cassettes")
    record_mode_str = vcr_config.get("record_mode", "none")

    # Marker can override
    if marker is not None:
        if marker.args:
            cassette_name = marker.args[0]
        marker_kwargs = dict(marker.kwargs)
        if "record_mode" in marker_kwargs:
            record_mode_str = marker_kwargs["record_mode"]
        if "cassette_dir" in marker_kwargs:
            cassette_dir = marker_kwargs["cassette_dir"]

    # CLI override
    cli_record_mode = request.config.getoption("--record-mode", default=None)
    if cli_record_mode is not None:
        record_mode_str = cli_record_mode

    record_mode = RecordMode.from_str(record_mode_str)

    # Resolve cassette path: {test_dir}/cassettes/{test_file_stem}/{cassette_name}
    test_file = Path(str(request.fspath))
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

    ignore_localhost = vcr_config.get("ignore_localhost", False)

    cassette = Cassette(
        cassette_path,
        record_mode=record_mode,
        match_config=match_config,
        security_config=security_config,
        ignore_localhost=ignore_localhost,
    )
    cassette.load()

    # Track loaded cassette paths for orphan detection
    _loaded_cassettes = getattr(request.config, "_vcr_loaded_cassettes", None)
    if _loaded_cassettes is not None:
        _loaded_cassettes.add(os.path.abspath(cassette_path))

    yield cassette  # type: ignore[misc]

    cassette.save()
