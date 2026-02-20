from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from vcr_but_better._core import Cassette as RustCassette
from vcr_but_better._types import CassetteConfig
from vcr_but_better.pytest_plugin.fixtures import _resolve_cassette
from vcr_but_better.pytest_plugin.markers import configure
from vcr_but_better.pytest_plugin.orphans import check_orphans, session_finish
from vcr_but_better.recording import RecordMode


class TestConfigure:
    def test_registers_marker(self) -> None:
        config = MagicMock()
        configure(config)
        config.addinivalue_line.assert_called_once()

    def test_no_option_attribute(self) -> None:
        class ConfigWithoutOption:
            def addinivalue_line(self, name: str, line: str) -> None:
                pass

        configure(ConfigWithoutOption())


class TestCheckOrphans:
    def test_finds_orphaned_files(self, tmp_path: object) -> None:
        cassette_dir = str(tmp_path)
        Path(os.path.join(cassette_dir, "used.yaml")).write_text("---")
        Path(os.path.join(cassette_dir, "orphan.yaml")).write_text("---")
        Path(os.path.join(cassette_dir, "orphan2.yml")).write_text("---")

        loaded = {os.path.abspath(os.path.join(cassette_dir, "used.yaml"))}
        orphans = check_orphans(cassette_dir, loaded)

        assert "orphan.yaml" in orphans
        assert "orphan2.yml" in orphans
        assert "used.yaml" not in orphans

    def test_no_orphans(self, tmp_path: object) -> None:
        cassette_dir = str(tmp_path)
        Path(os.path.join(cassette_dir, "used.yaml")).write_text("---")

        loaded = {os.path.abspath(os.path.join(cassette_dir, "used.yaml"))}
        orphans = check_orphans(cassette_dir, loaded)

        assert orphans == []

    def test_ignores_non_yaml_files(self, tmp_path: object) -> None:
        cassette_dir = str(tmp_path)
        Path(os.path.join(cassette_dir, "readme.txt")).write_text("not a cassette")
        Path(os.path.join(cassette_dir, "data.json")).write_text("{}")

        orphans = check_orphans(cassette_dir, set())
        assert orphans == []


class TestSessionFinish:
    def test_no_orphan_dir(self) -> None:
        config = MagicMock()
        config.getoption.return_value = None
        session = MagicMock()
        session.config = config
        session_finish(session)

    def test_warns_on_orphans(self, tmp_path: object) -> None:
        cassette_dir = str(tmp_path)
        Path(os.path.join(cassette_dir, "orphan.yaml")).write_text("---")

        config = MagicMock()
        config.getoption.return_value = cassette_dir
        config._vcr_loaded_cassettes = set()
        session = MagicMock()
        session.config = config

        with pytest.warns(UserWarning, match="orphaned cassette"):
            session_finish(session)

    def test_no_warning_when_no_orphans(self, tmp_path: object) -> None:
        cassette_dir = str(tmp_path)
        yaml_path = os.path.join(cassette_dir, "used.yaml")
        Path(yaml_path).write_text("---")

        config = MagicMock()
        config.getoption.return_value = cassette_dir
        config._vcr_loaded_cassettes = {os.path.abspath(yaml_path)}
        session = MagicMock()
        session.config = config

        session_finish(session)


class TestResolveCassette:
    def test_default_config(self, tmp_path: object) -> None:
        test_dir = str(tmp_path)
        cassette_dir = os.path.join(test_dir, "cassettes", "test_example")
        os.makedirs(cassette_dir, exist_ok=True)
        RustCassette().save(os.path.join(cassette_dir, "test_func.yaml"))

        cassette, interceptors = _resolve_cassette(
            node_name="test_func",
            marker_args=(),
            marker_kwargs={},
            vcr_config=CassetteConfig(record_mode="none", cassette_dir="cassettes"),
            cli_record_mode=None,
            test_fspath=os.path.join(test_dir, "test_example.py"),
        )

        assert cassette.path.endswith("test_func.yaml")
        assert cassette.record_mode == RecordMode.NONE
        assert len(interceptors) == 1

    def test_custom_cassette_name(self, tmp_path: object) -> None:
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

    def test_marker_kwargs_override(self, tmp_path: object) -> None:
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

    def test_cli_record_mode_override(self, tmp_path: object) -> None:
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

    def test_security_config_from_vcr_config(self, tmp_path: object) -> None:
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
                filtered_headers=["x-api-key"],
                filtered_query_params=["token"],
                body_scrub_patterns=["secret"],
                filter_replacement="[HIDDEN]",
            ),
            cli_record_mode=None,
            test_fspath=os.path.join(test_dir, "test_example.py"),
        )

        assert cassette is not None
