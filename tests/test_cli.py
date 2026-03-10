from __future__ import annotations

from pathlib import Path

import pytest

from cassetter._core import Body, Cassette, HttpInteraction, HttpRequest, HttpResponse
from cassetter.cli import main


@pytest.fixture()
def yaml_cassette(tmp_path: Path) -> str:
    path = str(tmp_path / "test.yaml")
    c = Cassette()
    c.add_interaction(
        HttpInteraction(
            HttpRequest("GET", "https://example.com/api"),
            HttpResponse(200, body=Body("json", {"ok": True})),
            "2026-01-01T00:00:00Z",
        )
    )
    c.save(path)
    return path


def test_convert_yaml_to_toml(yaml_cassette: str, tmp_path: Path) -> None:
    dst = str(tmp_path / "out.toml")
    main(["convert", yaml_cassette, dst])

    loaded = Cassette.load(dst)
    assert len(loaded) == 1
    assert loaded.interactions[0].request.method == "GET"


def test_convert_toml_to_yaml(yaml_cassette: str, tmp_path: Path) -> None:
    toml_path = str(tmp_path / "intermediate.toml")
    main(["convert", yaml_cassette, toml_path])

    yaml_path = str(tmp_path / "back.yaml")
    main(["convert", toml_path, yaml_path])

    loaded = Cassette.load(yaml_path)
    assert len(loaded) == 1
    assert loaded.interactions[0].response.body.content == {"ok": True}


def test_convert_refuses_overwrite(yaml_cassette: str, tmp_path: Path) -> None:
    dst = str(tmp_path / "out.toml")
    main(["convert", yaml_cassette, dst])

    with pytest.raises(SystemExit, match="1"):
        main(["convert", yaml_cassette, dst])


def test_convert_force_overwrite(yaml_cassette: str, tmp_path: Path) -> None:
    dst = str(tmp_path / "out.toml")
    main(["convert", yaml_cassette, dst])
    main(["convert", yaml_cassette, dst, "--force"])

    loaded = Cassette.load(dst)
    assert len(loaded) == 1


def test_convert_missing_source(tmp_path: Path) -> None:
    with pytest.raises(SystemExit, match="1"):
        main(["convert", str(tmp_path / "nope.yaml"), str(tmp_path / "out.toml")])


def test_convert_directory_to_format(tmp_path: Path) -> None:
    src_dir = tmp_path / "cassettes"
    src_dir.mkdir()
    for name in ("a.yaml", "b.yaml"):
        c = Cassette()
        c.add_interaction(
            HttpInteraction(
                HttpRequest("GET", f"https://example.com/{name}"),
                HttpResponse(200),
                "2026-01-01T00:00:00Z",
            )
        )
        c.save(str(src_dir / name))

    main(["convert", str(src_dir), "toml"])

    assert (src_dir / "a.toml").exists()
    assert (src_dir / "b.toml").exists()
    assert Cassette.load(str(src_dir / "a.toml")).interactions[0].request.uri == "https://example.com/a.yaml"


def test_convert_directory_to_directory(tmp_path: Path) -> None:
    src_dir = tmp_path / "src"
    src_dir.mkdir()
    c = Cassette()
    c.add_interaction(
        HttpInteraction(
            HttpRequest("POST", "https://example.com/data"),
            HttpResponse(201),
            "2026-01-01T00:00:00Z",
        )
    )
    c.save(str(src_dir / "test.yaml"))

    out_dir = tmp_path / "dst"
    main(["convert", str(src_dir), str(out_dir), "--to", "toml"])

    assert (out_dir / "test.toml").exists()
    loaded = Cassette.load(str(out_dir / "test.toml"))
    assert loaded.interactions[0].request.method == "POST"


def test_convert_directory_skips_existing(tmp_path: Path) -> None:
    src_dir = tmp_path / "cassettes"
    src_dir.mkdir()
    c = Cassette()
    c.add_interaction(
        HttpInteraction(
            HttpRequest("GET", "https://example.com"),
            HttpResponse(200),
            "2026-01-01T00:00:00Z",
        )
    )
    c.save(str(src_dir / "test.yaml"))

    main(["convert", str(src_dir), "toml"])
    assert (src_dir / "test.toml").exists()

    # Second run without --force should skip
    main(["convert", str(src_dir), "toml"])


def test_convert_no_command() -> None:
    with pytest.raises(SystemExit, match="1"):
        main([])


def test_convert_empty_directory(tmp_path: Path) -> None:
    empty = tmp_path / "empty"
    empty.mkdir()
    with pytest.raises(SystemExit, match="1"):
        main(["convert", str(empty), "toml"])
