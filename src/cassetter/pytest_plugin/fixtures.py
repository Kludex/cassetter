from __future__ import annotations

import os
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from cassetter._core import MatchConfig, SecurityConfig
from cassetter._state import _current_cassette, acquire_patches, release_patches
from cassetter._types import CassetteConfig
from cassetter.cassette import Cassette
from cassetter.context import resolve_interceptors
from cassetter.intercept._base import InterceptorProtocol
from cassetter.recording import RecordMode


@pytest.fixture(scope="module")
def vcr_config() -> CassetteConfig:
    """Override this fixture to provide default VCR configuration."""
    return CassetteConfig()


@pytest.fixture(scope="module")
def vcr_cassette_dir(request: pytest.FixtureRequest) -> str:
    """Per-module cassette directory, matching pytest-recording's convention.

    Defaults to ``{test_dir}/cassettes/{test_file_stem}``.
    Override this fixture to customize the cassette storage location.
    """
    test_file = Path(str(request.path))
    return str(test_file.parent / "cassettes" / test_file.stem)


def _resolve_cassette(
    node_name: str,
    marker_args: tuple[Any, ...],
    marker_kwargs: dict[str, Any],
    vcr_config: CassetteConfig,
    cli_record_mode: str | None,
    test_fspath: str,
    vcr_cassette_dir: str | None = None,
) -> tuple[Cassette, list[type[InterceptorProtocol]]]:
    """Resolve cassette configuration and create a Cassette instance."""
    cassette_name = node_name + ".yaml"
    record_mode_str = vcr_config.get("record_mode", "none")

    # Marker can override
    if marker_args:
        cassette_name = marker_args[0]
    if "record_mode" in marker_kwargs:
        record_mode_str = marker_kwargs["record_mode"]

    # CLI override
    if cli_record_mode is not None:
        record_mode_str = cli_record_mode

    record_mode = RecordMode.from_str(record_mode_str)

    # Resolve cassette directory: vcr_cassette_dir fixture > marker > vcr_config > default
    if "cassette_dir" in marker_kwargs:
        test_file = Path(test_fspath)
        test_dir = str(test_file.parent)
        cassette_dir = os.path.join(test_dir, marker_kwargs["cassette_dir"], test_file.stem)
    elif vcr_cassette_dir is not None:
        cassette_dir = vcr_cassette_dir
    elif "cassette_dir" in vcr_config:
        test_file = Path(test_fspath)
        test_dir = str(test_file.parent)
        cassette_dir = os.path.join(test_dir, vcr_config["cassette_dir"], test_file.stem)
    else:
        test_file = Path(test_fspath)
        test_dir = str(test_file.parent)
        cassette_dir = os.path.join(test_dir, "cassettes", test_file.stem)

    cassette_path = os.path.join(cassette_dir, cassette_name)

    match_config = MatchConfig(
        match_on=vcr_config.get("match_on"),
        ignore_json_paths=vcr_config.get("ignore_json_paths"),
    )

    security_kwargs: dict[str, Any] = {}
    if "filter_headers" in vcr_config:
        security_kwargs["filter_headers"] = vcr_config["filter_headers"]
    # Accept both cassetter's `filter_query_params` and VCR's `filter_query_parameters`
    filter_qp = vcr_config.get("filter_query_params") or vcr_config.get("filter_query_parameters")
    if filter_qp:
        security_kwargs["filter_query_params"] = filter_qp
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
    interceptor_classes = resolve_interceptors(intercept_names)
    return cassette, interceptor_classes


@pytest.fixture(autouse=True)
def cassette(
    request: pytest.FixtureRequest, vcr_config: CassetteConfig, vcr_cassette_dir: str
) -> Iterator[Cassette | None]:
    """Activates cassette recording/replay for tests marked with @pytest.mark.vcr."""
    marker = request.node.get_closest_marker("vcr")
    if marker is None:
        yield None
        return

    cli_record_mode = request.config.getoption("--record-mode", default=None)

    # Include class name for class-based tests (e.g. TestOpenAI.test_query)
    cls = request.node.cls
    node_name = f"{cls.__name__}.{request.node.name}" if cls else request.node.name

    cassette, interceptor_classes = _resolve_cassette(
        node_name=node_name,
        marker_args=marker.args,
        marker_kwargs=dict(marker.kwargs),
        vcr_config=vcr_config,
        cli_record_mode=cli_record_mode,
        test_fspath=str(request.path),
        vcr_cassette_dir=vcr_cassette_dir,
    )

    # Track loaded cassette paths for orphan detection
    _loaded_cassettes = getattr(request.config, "_vcr_loaded_cassettes", None)
    if _loaded_cassettes is not None:
        _loaded_cassettes.add(os.path.abspath(cassette.path))

    acquire_patches(interceptor_classes)
    token = _current_cassette.set(cassette)

    yield cassette

    # Reset context and release patches
    _current_cassette.reset(token)
    release_patches(interceptor_classes)
    cassette.save()


@pytest.fixture
def vcr(cassette: Cassette | None) -> Cassette | None:
    """Alias for the ``cassette`` fixture, for pytest-recording compatibility."""
    return cassette
