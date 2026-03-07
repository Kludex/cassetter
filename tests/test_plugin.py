from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from cassetter._core import Body, Cassette as RustCassette, HttpInteraction, HttpRequest, HttpResponse
from cassetter._types import CassetteConfig
from cassetter.cassette import CassetteExpiredError, CassetteExpiredWarning
from cassetter.pytest_plugin.fixtures import _resolve_cassette
from cassetter.pytest_plugin.markers import configure
from cassetter.pytest_plugin.orphans import check_orphans, session_finish
from cassetter.recording import RecordMode


def test_configure_registers_marker() -> None:
    config = MagicMock()
    configure(config)
    config.addinivalue_line.assert_called_once()


def test_configure_no_option_attribute() -> None:
    class ConfigWithoutOption:
        def addinivalue_line(self, name: str, line: str) -> None:
            pass

    configure(ConfigWithoutOption())


def test_check_orphans_finds_orphaned_files(tmp_path: object) -> None:
    cassette_dir = str(tmp_path)
    Path(os.path.join(cassette_dir, "used.yaml")).write_text("---")
    Path(os.path.join(cassette_dir, "orphan.yaml")).write_text("---")
    Path(os.path.join(cassette_dir, "orphan2.yml")).write_text("---")

    loaded = {os.path.abspath(os.path.join(cassette_dir, "used.yaml"))}
    orphans = check_orphans(cassette_dir, loaded)

    assert "orphan.yaml" in orphans
    assert "orphan2.yml" in orphans
    assert "used.yaml" not in orphans


def test_check_orphans_no_orphans(tmp_path: object) -> None:
    cassette_dir = str(tmp_path)
    Path(os.path.join(cassette_dir, "used.yaml")).write_text("---")

    loaded = {os.path.abspath(os.path.join(cassette_dir, "used.yaml"))}
    orphans = check_orphans(cassette_dir, loaded)

    assert orphans == []


def test_check_orphans_ignores_non_yaml_files(tmp_path: object) -> None:
    cassette_dir = str(tmp_path)
    Path(os.path.join(cassette_dir, "readme.txt")).write_text("not a cassette")
    Path(os.path.join(cassette_dir, "data.json")).write_text("{}")

    orphans = check_orphans(cassette_dir, set())
    assert orphans == []


def test_session_finish_no_orphan_dir() -> None:
    config = MagicMock()
    config.getoption.return_value = None
    session = MagicMock()
    session.config = config
    session_finish(session)


def test_session_finish_warns_on_orphans(tmp_path: object) -> None:
    cassette_dir = str(tmp_path)
    Path(os.path.join(cassette_dir, "orphan.yaml")).write_text("---")

    config = MagicMock()
    config.getoption.return_value = cassette_dir
    config._vcr_loaded_cassettes = set()
    session = MagicMock()
    session.config = config

    with pytest.warns(UserWarning, match="orphaned cassette"):
        session_finish(session)


def test_session_finish_no_warning_when_no_orphans(tmp_path: object) -> None:
    cassette_dir = str(tmp_path)
    yaml_path = os.path.join(cassette_dir, "used.yaml")
    Path(yaml_path).write_text("---")

    config = MagicMock()
    config.getoption.return_value = cassette_dir
    config._vcr_loaded_cassettes = {os.path.abspath(yaml_path)}
    session = MagicMock()
    session.config = config

    session_finish(session)


def test_resolve_cassette_default_config(tmp_path: object) -> None:
    test_dir = str(tmp_path)
    cassette_dir = os.path.join(test_dir, "cassettes", "test_example")
    os.makedirs(cassette_dir, exist_ok=True)
    RustCassette().save(os.path.join(cassette_dir, "test_func.yaml"))

    cassette, interceptor_classes = _resolve_cassette(
        node_name="test_func",
        marker_args=(),
        marker_kwargs={},
        vcr_config=CassetteConfig(record_mode="none", cassette_dir="cassettes"),
        cli_record_mode=None,
        test_fspath=os.path.join(test_dir, "test_example.py"),
    )

    assert cassette.path.endswith("test_func.yaml")
    assert cassette.record_mode == RecordMode.NONE
    assert len(interceptor_classes) >= 1


def test_resolve_cassette_custom_cassette_name(tmp_path: object) -> None:
    test_dir = str(tmp_path)
    cassette_dir = os.path.join(test_dir, "cassettes", "test_example")
    os.makedirs(cassette_dir, exist_ok=True)
    RustCassette().save(os.path.join(cassette_dir, "custom.yaml"))

    cassette, _ = _resolve_cassette(
        node_name="test_func",
        marker_args=("custom.yaml",),
        marker_kwargs={},
        vcr_config=CassetteConfig(record_mode="none", cassette_dir="cassettes"),
        cli_record_mode=None,
        test_fspath=os.path.join(test_dir, "test_example.py"),
    )

    assert cassette.path.endswith("custom.yaml")


def test_resolve_cassette_marker_kwargs_override(tmp_path: object) -> None:
    test_dir = str(tmp_path)
    alt_dir = os.path.join(test_dir, "alt", "test_example")
    os.makedirs(alt_dir, exist_ok=True)
    RustCassette().save(os.path.join(alt_dir, "test_func.yaml"))

    cassette, _ = _resolve_cassette(
        node_name="test_func",
        marker_args=(),
        marker_kwargs={"record_mode": "none", "cassette_dir": "alt"},
        vcr_config=CassetteConfig(),
        cli_record_mode=None,
        test_fspath=os.path.join(test_dir, "test_example.py"),
    )

    assert "alt" in cassette.path


def test_resolve_cassette_cli_record_mode_override(tmp_path: object) -> None:
    test_dir = str(tmp_path)
    cassette_dir = os.path.join(test_dir, "cassettes", "test_example")
    os.makedirs(cassette_dir, exist_ok=True)
    RustCassette().save(os.path.join(cassette_dir, "test_func.yaml"))

    cassette, _ = _resolve_cassette(
        node_name="test_func",
        marker_args=(),
        marker_kwargs={},
        vcr_config=CassetteConfig(record_mode="all", cassette_dir="cassettes"),
        cli_record_mode="none",
        test_fspath=os.path.join(test_dir, "test_example.py"),
    )

    assert cassette.record_mode == RecordMode.NONE


def test_resolve_cassette_security_config_from_vcr_config(tmp_path: object) -> None:
    test_dir = str(tmp_path)
    cassette_dir = os.path.join(test_dir, "cassettes", "test_example")
    os.makedirs(cassette_dir, exist_ok=True)
    RustCassette().save(os.path.join(cassette_dir, "test_func.yaml"))

    cassette, _ = _resolve_cassette(
        node_name="test_func",
        marker_args=(),
        marker_kwargs={},
        vcr_config=CassetteConfig(
            record_mode="none",
            cassette_dir="cassettes",
            filter_headers=["x-api-key"],
            filter_query_parameters=["token"],
            body_scrub_patterns=["secret"],
            filter_replacement="[HIDDEN]",
        ),
        cli_record_mode=None,
        test_fspath=os.path.join(test_dir, "test_example.py"),
    )

    assert cassette is not None


def test_resolve_cassette_max_age_from_vcr_config(tmp_path: object) -> None:
    test_dir = str(tmp_path)
    cassette_dir = os.path.join(test_dir, "cassettes", "test_example")
    os.makedirs(cassette_dir, exist_ok=True)
    path = os.path.join(cassette_dir, "test_func.yaml")
    c = RustCassette()
    c.add_interaction(
        HttpInteraction(
            request=HttpRequest("GET", "https://example.com/"),
            response=HttpResponse(200, body=Body("text", "ok")),
            recorded_at="2020-01-01T00:00:00Z",
        )
    )
    c.save(path)

    with pytest.warns(CassetteExpiredWarning):
        _resolve_cassette(
            node_name="test_func",
            marker_args=(),
            marker_kwargs={},
            vcr_config=CassetteConfig(record_mode="none", cassette_dir="cassettes", max_age="1d"),
            cli_record_mode=None,
            test_fspath=os.path.join(test_dir, "test_example.py"),
        )


def test_resolve_cassette_max_age_marker_override(tmp_path: object) -> None:
    test_dir = str(tmp_path)
    cassette_dir = os.path.join(test_dir, "cassettes", "test_example")
    os.makedirs(cassette_dir, exist_ok=True)
    path = os.path.join(cassette_dir, "test_func.yaml")
    c = RustCassette()
    c.add_interaction(
        HttpInteraction(
            request=HttpRequest("GET", "https://example.com/"),
            response=HttpResponse(200, body=Body("text", "ok")),
            recorded_at="2020-01-01T00:00:00Z",
        )
    )
    c.save(path)

    with pytest.raises(CassetteExpiredError):
        _resolve_cassette(
            node_name="test_func",
            marker_args=(),
            marker_kwargs={"max_age": "1d", "on_expiry": "fail"},
            vcr_config=CassetteConfig(record_mode="none", cassette_dir="cassettes"),
            cli_record_mode=None,
            test_fspath=os.path.join(test_dir, "test_example.py"),
        )


def test_resolve_cassette_vcr_cassette_dir_fixture(tmp_path: object) -> None:
    cassette_dir = os.path.join(str(tmp_path), "custom_cassettes")
    os.makedirs(cassette_dir, exist_ok=True)
    RustCassette().save(os.path.join(cassette_dir, "test_func.yaml"))

    cassette, _ = _resolve_cassette(
        node_name="test_func",
        marker_args=(),
        marker_kwargs={},
        vcr_config=CassetteConfig(record_mode="none"),
        cli_record_mode=None,
        test_fspath=os.path.join(str(tmp_path), "test_example.py"),
        vcr_cassette_dir=cassette_dir,
    )

    assert cassette.path == os.path.join(cassette_dir, "test_func.yaml")


def test_resolve_cassette_marker_cassette_dir_overrides_fixture(tmp_path: object) -> None:
    marker_dir = os.path.join(str(tmp_path), "marker_dir", "test_example")
    os.makedirs(marker_dir, exist_ok=True)
    RustCassette().save(os.path.join(marker_dir, "test_func.yaml"))

    cassette, _ = _resolve_cassette(
        node_name="test_func",
        marker_args=(),
        marker_kwargs={"cassette_dir": "marker_dir"},
        vcr_config=CassetteConfig(record_mode="none"),
        cli_record_mode=None,
        test_fspath=os.path.join(str(tmp_path), "test_example.py"),
        vcr_cassette_dir=os.path.join(str(tmp_path), "fixture_dir"),
    )

    assert "marker_dir" in cassette.path


def test_resolve_cassette_filter_query_parameters(tmp_path: object) -> None:
    test_dir = str(tmp_path)
    cassette_dir = os.path.join(test_dir, "cassettes", "test_example")
    os.makedirs(cassette_dir, exist_ok=True)
    RustCassette().save(os.path.join(cassette_dir, "test_func.yaml"))

    cassette, _ = _resolve_cassette(
        node_name="test_func",
        marker_args=(),
        marker_kwargs={},
        vcr_config=CassetteConfig(
            record_mode="none",
            cassette_dir="cassettes",
            filter_query_parameters=["api_key", "token"],
        ),
        cli_record_mode=None,
        test_fspath=os.path.join(test_dir, "test_example.py"),
    )

    assert cassette is not None
