from __future__ import annotations

import os
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from cassetter import Cassetter
from cassetter._core import Body, Cassette as RustCassette, HttpInteraction, HttpRequest, HttpResponse
from cassetter._types import CassetteConfig
from cassetter.cassette import CassetteExpiredError, CassetteExpiredWarning
from cassetter.pytest_plugin.fixtures import _resolve_cassette
from cassetter.pytest_plugin.markers import configure
from cassetter.pytest_plugin.orphans import (
    LOADED_CASSETTES,
    add_options,
    check_orphans,
    node_down,
    session_finish,
)
from cassetter.recording import RecordMode


def test_configure_registers_marker() -> None:
    config = MagicMock()
    configure(config)
    config.addinivalue_line.assert_called_once()


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


def controller_config() -> MagicMock:
    """A config mock without `workerinput`, i.e. not an xdist worker."""
    config = MagicMock()
    del config.workerinput
    config.stash = pytest.Stash()
    return config


def test_session_finish_no_orphan_dir() -> None:
    config = controller_config()
    config.getoption.return_value = None
    session = MagicMock()
    session.config = config
    session_finish(session)


def test_session_finish_warns_on_orphans(tmp_path: object) -> None:
    cassette_dir = str(tmp_path)
    Path(os.path.join(cassette_dir, "orphan.yaml")).write_text("---")

    config = controller_config()
    config.getoption.return_value = cassette_dir
    session = MagicMock()
    session.config = config

    with pytest.warns(UserWarning, match="orphaned cassette"):
        session_finish(session)


def test_session_finish_no_warning_when_no_orphans(tmp_path: object) -> None:
    cassette_dir = str(tmp_path)
    yaml_path = os.path.join(cassette_dir, "used.yaml")
    Path(yaml_path).write_text("---")

    config = controller_config()
    config.getoption.return_value = cassette_dir
    config.stash[LOADED_CASSETTES] = {os.path.abspath(yaml_path)}
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


def test_resolve_cassette_from_cassetter(tmp_path: object) -> None:
    library_dir = os.path.join(str(tmp_path), "shared_cassettes")
    os.makedirs(library_dir, exist_ok=True)
    RustCassette().save(os.path.join(library_dir, "test_func.yaml"))

    cassette, _ = _resolve_cassette(
        node_name="test_func",
        marker_args=(),
        marker_kwargs={},
        vcr_config=Cassetter(cassette_library_dir=library_dir),
        cli_record_mode=None,
        test_fspath=os.path.join(str(tmp_path), "test_example.py"),
        vcr_cassette_dir=os.path.join(str(tmp_path), "fixture_dir"),
    )

    assert cassette.path == os.path.join(library_dir, "test_func.yaml")


def test_resolve_cassette_from_cassetter_defaults_to_none_record_mode(tmp_path: object) -> None:
    """An unset record mode means `none` under pytest, even though `use_cassette` defaults to `once`."""
    cassette_dir = os.path.join(str(tmp_path), "cassettes")
    os.makedirs(cassette_dir, exist_ok=True)
    RustCassette().save(os.path.join(cassette_dir, "test_func.yaml"))

    cassette, _ = _resolve_cassette(
        node_name="test_func",
        marker_args=(),
        marker_kwargs={},
        vcr_config=Cassetter(),
        cli_record_mode=None,
        test_fspath=os.path.join(str(tmp_path), "test_example.py"),
        vcr_cassette_dir=cassette_dir,
    )

    assert cassette.record_mode == RecordMode.NONE


def test_resolve_cassette_marker_dir_overrides_cassette_library_dir(tmp_path: object) -> None:
    marker_dir = os.path.join(str(tmp_path), "marker_dir", "test_example")
    os.makedirs(marker_dir, exist_ok=True)
    RustCassette().save(os.path.join(marker_dir, "test_func.yaml"))

    cassette, _ = _resolve_cassette(
        node_name="test_func",
        marker_args=(),
        marker_kwargs={"cassette_dir": "marker_dir"},
        vcr_config=Cassetter(cassette_library_dir=os.path.join(str(tmp_path), "shared")),
        cli_record_mode=None,
        test_fspath=os.path.join(str(tmp_path), "test_example.py"),
    )

    assert cassette.path == os.path.join(marker_dir, "test_func.yaml")


def test_resolve_cassette_ini_on_expiry(tmp_path: object) -> None:
    cassette_dir = os.path.join(str(tmp_path), "cassettes")
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
            marker_kwargs={},
            vcr_config=Cassetter(max_age="1d"),
            cli_record_mode=None,
            test_fspath=os.path.join(str(tmp_path), "test_example.py"),
            vcr_cassette_dir=cassette_dir,
            ini_on_expiry="fail",
        )


def test_resolve_cassette_ignores_unknown_vcr_config_keys(tmp_path: object) -> None:
    """Keys VCR.py supports but cassetter handles automatically are no-ops, not errors."""
    cassette_dir = os.path.join(str(tmp_path), "cassettes")
    os.makedirs(cassette_dir, exist_ok=True)
    RustCassette().save(os.path.join(cassette_dir, "test_func.yaml"))

    # An unknown vcrpy-compat key must be tolerated, not rejected.
    vcr_config: CassetteConfig = {
        "record_mode": "none",
        "decode_compressed_response": True,  # type: ignore[typeddict-unknown-key]
    }

    cassette, _ = _resolve_cassette(
        node_name="test_func",
        marker_args=(),
        marker_kwargs={},
        vcr_config=vcr_config,
        cli_record_mode=None,
        test_fspath=os.path.join(str(tmp_path), "test_example.py"),
        vcr_cassette_dir=cassette_dir,
    )

    assert cassette.record_mode == RecordMode.NONE


def test_ini_options_registered() -> None:
    """The README-documented vcr_max_age / vcr_on_expiry ini options exist."""
    parser = MagicMock()
    add_options(parser)
    ini_names = [call.args[0] for call in parser.addini.call_args_list]
    assert ini_names == ["vcr_max_age", "vcr_on_expiry"]


def test_check_orphans_includes_toml(tmp_path: object) -> None:
    cassette_dir = str(tmp_path)
    Path(os.path.join(cassette_dir, "orphan.toml")).write_text("---")
    assert check_orphans(cassette_dir, set()) == ["orphan.toml"]


def test_resolve_cassette_sanitizes_forbidden_filename_chars(tmp_path: object) -> None:
    """Node names keep pytest-recording's sanitization so vcrpy-recorded cassettes resolve."""
    test_dir = str(tmp_path)
    cassette_dir = os.path.join(test_dir, "cassettes", "test_example")
    os.makedirs(cassette_dir, exist_ok=True)
    sanitized = "test_func[anthropic-claude-sonnet-4-5-openai-responses-gpt-5.4].yaml"
    RustCassette().save(os.path.join(cassette_dir, sanitized))

    cassette, _ = _resolve_cassette(
        node_name="test_func[anthropic:claude-sonnet-4-5-openai-responses:gpt-5.4]",
        marker_args=(),
        marker_kwargs={},
        vcr_config=CassetteConfig(record_mode="none", cassette_dir="cassettes"),
        cli_record_mode=None,
        test_fspath=os.path.join(test_dir, "test_example.py"),
    )

    assert os.path.basename(cassette.path) == sanitized
    assert os.path.exists(cassette.path)


@pytest.mark.skipif(sys.platform == "win32", reason="':' is not a legal file name character")
def test_resolve_cassette_keeps_existing_unsanitized_name(tmp_path: object) -> None:
    """A cassette recorded before names were sanitized keeps replaying."""
    test_dir = str(tmp_path)
    cassette_dir = os.path.join(test_dir, "cassettes", "test_example")
    os.makedirs(cassette_dir, exist_ok=True)
    node_name = "test_func[anthropic:claude-sonnet-4-5]"
    RustCassette().save(os.path.join(cassette_dir, node_name + ".yaml"))

    cassette, _ = _resolve_cassette(
        node_name=node_name,
        marker_args=(),
        marker_kwargs={},
        vcr_config=CassetteConfig(record_mode="none", cassette_dir="cassettes"),
        cli_record_mode=None,
        test_fspath=os.path.join(test_dir, "test_example.py"),
    )

    assert os.path.basename(cassette.path) == node_name + ".yaml"
    assert os.path.exists(cassette.path)


def test_resolve_cassette_records_under_sanitized_name_when_neither_exists(tmp_path: object) -> None:
    """With nothing on disk, a new cassette takes the sanitized name."""
    test_dir = str(tmp_path)

    cassette, _ = _resolve_cassette(
        node_name="test_func[anthropic:claude]",
        marker_args=(),
        marker_kwargs={},
        vcr_config=CassetteConfig(record_mode="all", cassette_dir="cassettes"),
        cli_record_mode=None,
        test_fspath=os.path.join(test_dir, "test_example.py"),
    )

    assert os.path.basename(cassette.path) == "test_func[anthropic-claude].yaml"


def test_resolve_cassette_passes_uri_normalizer(tmp_path: object) -> None:
    test_dir = str(tmp_path)
    cassette_dir = os.path.join(test_dir, "cassettes", "test_example")
    os.makedirs(cassette_dir, exist_ok=True)
    c = RustCassette()
    c.add_interaction(
        HttpInteraction(
            request=HttpRequest("GET", "https://svc.us-east-2.example.com/run"),
            response=HttpResponse(200, body=Body("text", "ok")),
            recorded_at="2026-01-01T00:00:00Z",
        )
    )
    c.save(os.path.join(cassette_dir, "test_func.yaml"))

    cassette, _ = _resolve_cassette(
        node_name="test_func",
        marker_args=(),
        marker_kwargs={},
        vcr_config=CassetteConfig(
            record_mode="none",
            cassette_dir="cassettes",
            uri_normalizer=lambda uri: uri.replace("us-east-1", "R").replace("us-east-2", "R"),
        ),
        cli_record_mode=None,
        test_fspath=os.path.join(test_dir, "test_example.py"),
    )

    response = cassette.play("GET", "https://svc.us-east-1.example.com/run", {}, None)
    assert response.body.content == "ok"


def test_worker_ships_loaded_cassettes_to_controller() -> None:
    """An xdist worker reports nothing itself; it hands its shard to the controller."""
    config = MagicMock()
    config.workerinput = {"workerid": "gw0"}
    config.workeroutput = {}
    config.stash = pytest.Stash()
    config.stash[LOADED_CASSETTES] = {"/cassettes/a.yaml"}
    session = MagicMock()
    session.config = config

    session_finish(session)

    assert config.workeroutput["vcr_loaded_cassettes"] == ["/cassettes/a.yaml"]


def test_controller_aggregates_worker_shards(tmp_path: object) -> None:
    """Every worker's cassettes count as used, not just the controller's."""
    cassette_dir = str(tmp_path)
    for name in ("a.yaml", "b.yaml"):
        Path(os.path.join(cassette_dir, name)).write_text("---")

    config = controller_config()
    config.getoption.return_value = cassette_dir

    for name in ("a.yaml", "b.yaml"):
        node = MagicMock()
        node.config = config
        node.workeroutput = {"vcr_loaded_cassettes": [os.path.abspath(os.path.join(cassette_dir, name))]}
        node_down(node)

    session = MagicMock()
    session.config = config
    session_finish(session)


def test_node_down_without_workeroutput_is_ignored() -> None:
    node = MagicMock()
    node.workeroutput = {}
    node_down(node)


def test_aggregator_hook_forwards_to_node_down() -> None:
    """The xdist hook runs in the controller process, which coverage cannot see."""
    from cassetter.pytest_plugin import _XdistOrphanAggregator

    config = controller_config()
    node = MagicMock()
    node.config = config
    node.workeroutput = {"vcr_loaded_cassettes": ["/cassettes/a.yaml"]}

    _XdistOrphanAggregator().pytest_testnodedown(node, None)

    assert config.stash[LOADED_CASSETTES] == {"/cassettes/a.yaml"}


def test_xdist_aggregator_registered_only_with_xdist() -> None:
    """The xdist hook is registered conditionally, so non-xdist users still load."""
    from cassetter.pytest_plugin import pytest_configure

    with_xdist = MagicMock()
    with_xdist.pluginmanager.hasplugin.return_value = True
    pytest_configure(with_xdist)
    assert with_xdist.pluginmanager.register.called

    without_xdist = MagicMock()
    without_xdist.pluginmanager.hasplugin.return_value = False
    pytest_configure(without_xdist)
    assert not without_xdist.pluginmanager.register.called
