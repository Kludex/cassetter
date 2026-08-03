from __future__ import annotations

import os
from collections.abc import Iterator, Mapping
from dataclasses import fields, replace
from pathlib import Path
from typing import Any, cast

import pytest

from cassetter._state import (
    acquire_patches,
    current_cassette,
    pop_fallback_cassette,
    push_fallback_cassette,
    release_patches,
)
from cassetter._types import CassetteConfig
from cassetter.cassette import Cassette
from cassetter.config import Cassetter
from cassetter.intercept._base import InterceptorProtocol
from cassetter.intercept._registry import resolve_interceptors
from cassetter.pytest_plugin.orphans import loaded_cassettes

_CASSETTER_FIELDS = {field.name for field in fields(Cassetter)}


@pytest.fixture(scope="module")
def vcr_config() -> CassetteConfig | Cassetter:
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


def _split_config(vcr_config: CassetteConfig | Cassetter) -> tuple[Cassetter, str | None]:
    """Split a `vcr_config` value into a configuration and the test-relative `cassette_dir`."""
    if isinstance(vcr_config, Cassetter):
        return vcr_config, None
    options: Mapping[str, Any] = vcr_config
    known = {name: value for name, value in options.items() if name in _CASSETTER_FIELDS}
    return Cassetter(**known), options.get("cassette_dir")


def _sanitized_file_name(node_name: str) -> str:
    """The cassette file name pytest-recording derives from `node_name`.

    Parametrize ids may contain characters that are forbidden in file names
    (e.g. ':' from model names), so cassettes recorded under vcrpy only resolve
    when they are replaced the same way.
    """
    for ch in "<>?%*:|\"'/\\":
        node_name = node_name.replace(ch, "-")
    return node_name + ".yaml"


def _existing_file_name(cassette_dir: str, name: str, legacy_name: str) -> str:
    """Prefer `legacy_name` when it is the only one on disk.

    Cassetter recorded under the raw node name before it sanitized them, and
    POSIX accepts those names, so such a cassette must keep replaying instead
    of being silently replaced by an empty one.
    """
    if name == legacy_name or os.path.exists(os.path.join(cassette_dir, name)):
        return name
    return legacy_name if os.path.exists(os.path.join(cassette_dir, legacy_name)) else name


def _resolve_cassette(
    node_name: str,
    marker_args: tuple[str, ...],
    marker_kwargs: CassetteConfig,
    vcr_config: CassetteConfig | Cassetter,
    cli_record_mode: str | None,
    test_fspath: str,
    vcr_cassette_dir: str | None = None,
    ini_max_age: str | None = None,
    ini_on_expiry: str | None = None,
) -> tuple[Cassette, list[type[InterceptorProtocol]]]:
    """Resolve cassette configuration and create a Cassette instance."""
    config, config_cassette_dir = _split_config(vcr_config)

    cassette_name = marker_args[0] if marker_args else _sanitized_file_name(node_name)

    record_mode = config.record_mode or "none"
    if "record_mode" in marker_kwargs:
        record_mode = marker_kwargs["record_mode"]
    if cli_record_mode is not None:
        record_mode = cli_record_mode

    test_file = Path(test_fspath)
    test_dir = str(test_file.parent)

    # marker > cassette_library_dir > vcr_cassette_dir fixture > vcr_config > default
    if "cassette_dir" in marker_kwargs:
        cassette_dir = os.path.join(test_dir, marker_kwargs["cassette_dir"], test_file.stem)
    elif config.cassette_library_dir is not None:
        cassette_dir = os.fspath(config.cassette_library_dir)
    elif vcr_cassette_dir is not None:
        cassette_dir = vcr_cassette_dir
    elif config_cassette_dir is not None:
        cassette_dir = os.path.join(test_dir, config_cassette_dir, test_file.stem)
    else:  # pragma: no cover - the vcr_cassette_dir fixture always supplies a directory
        cassette_dir = os.path.join(test_dir, "cassettes", test_file.stem)

    if not marker_args:
        cassette_name = _existing_file_name(cassette_dir, cassette_name, node_name + ".yaml")

    resolved = replace(
        config,
        cassette_library_dir=cassette_dir,
        record_mode=record_mode,
        max_age=marker_kwargs.get("max_age", config.max_age or ini_max_age),
        on_expiry=marker_kwargs.get("on_expiry", config.on_expiry or ini_on_expiry or "warn"),
    )
    cassette = resolved.cassette(cassette_name)
    cassette.load()

    return cassette, resolve_interceptors(config.intercept)


@pytest.fixture(autouse=True)
def cassette(
    request: pytest.FixtureRequest, vcr_config: CassetteConfig | Cassetter, vcr_cassette_dir: str
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
        marker_kwargs=cast(CassetteConfig, marker.kwargs),
        vcr_config=vcr_config,
        cli_record_mode=cli_record_mode,
        test_fspath=str(request.path),
        vcr_cassette_dir=vcr_cassette_dir,
        ini_max_age=request.config.getini("vcr_max_age") or None,
        ini_on_expiry=request.config.getini("vcr_on_expiry") or None,
    )

    # Track loaded cassette paths for orphan detection
    loaded_cassettes(request.config).add(os.path.abspath(cassette.path))

    acquire_patches(interceptor_classes)
    token = current_cassette.set(cassette)
    push_fallback_cassette(cassette)

    try:
        yield cassette
    finally:
        # Reset context and release patches even if the test errors out
        pop_fallback_cassette(cassette)
        current_cassette.reset(token)
        release_patches(interceptor_classes)
        cassette.save()


@pytest.fixture
def vcr(cassette: Cassette | None) -> Cassette | None:
    """Alias for the ``cassette`` fixture, for pytest-recording compatibility."""
    return cassette
