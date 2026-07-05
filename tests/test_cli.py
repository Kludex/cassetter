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


@pytest.fixture()
def secret_cassette(tmp_path: Path) -> str:
    """A VCR-era cassette carrying secrets in headers, query params, and bodies."""
    path = str(tmp_path / "secrets.yaml")
    c = Cassette()
    c.add_interaction(
        HttpInteraction(
            HttpRequest(
                "POST",
                "https://example.com/login?api_key=hunter2&page=1",
                {"authorization": ["Bearer tok123"], "accept": ["application/json"]},
                Body("json", {"password": "hunter2", "user": "alice"}),
            ),
            HttpResponse(
                200,
                {"set-cookie": ["session=abc"]},
                Body("json", {"access_token": "tok456", "ok": True}),
            ),
            "2026-01-01T00:00:00Z",
        )
    )
    c.save(path)
    return path


def test_convert_scrubs_by_default(secret_cassette: str, tmp_path: Path) -> None:
    dst = str(tmp_path / "clean.yaml")
    main(["convert", secret_cassette, dst])

    loaded = Cassette.load(dst)
    request = loaded.interactions[0].request
    response = loaded.interactions[0].response
    assert "authorization" not in request.headers
    assert request.headers["accept"] == ["application/json"]
    assert "hunter2" not in request.uri
    assert "page=1" in request.uri
    assert request.body.content["password"] == "[FILTERED]"
    assert request.body.content["user"] == "alice"
    assert "set-cookie" not in response.headers
    assert response.body.content["access_token"] == "[FILTERED]"
    assert response.body.content["ok"] is True


def test_convert_no_scrub_preserves_data(secret_cassette: str, tmp_path: Path) -> None:
    dst = str(tmp_path / "raw.yaml")
    main(["convert", secret_cassette, dst, "--no-scrub"])

    loaded = Cassette.load(dst)
    request = loaded.interactions[0].request
    assert request.headers["authorization"] == ["Bearer tok123"]
    assert "api_key=hunter2" in request.uri
    assert request.body.content["password"] == "hunter2"


def test_convert_in_place_requires_force(yaml_cassette: str) -> None:
    with pytest.raises(SystemExit, match="1"):
        main(["convert", yaml_cassette, yaml_cassette])


def test_convert_in_place_with_force(secret_cassette: str) -> None:
    main(["convert", secret_cassette, secret_cassette, "--force"])

    loaded = Cassette.load(secret_cassette)
    assert len(loaded) == 1
    assert "authorization" not in loaded.interactions[0].request.headers
    # No temp file left behind
    assert not Path(secret_cassette).with_suffix(".tmp.yaml").exists()


def test_convert_directory_in_place_requires_force(tmp_path: Path) -> None:
    src_dir = tmp_path / "cassettes"
    src_dir.mkdir()
    c = Cassette()
    c.add_interaction(
        HttpInteraction(
            HttpRequest("GET", "https://example.com", {"authorization": ["Bearer x"]}),
            HttpResponse(200),
            "2026-01-01T00:00:00Z",
        )
    )
    c.save(str(src_dir / "test.yaml"))

    # Without --force, same-path files are skipped and left untouched
    main(["convert", str(src_dir), "yaml"])
    loaded = Cassette.load(str(src_dir / "test.yaml"))
    assert loaded.interactions[0].request.headers["authorization"] == ["Bearer x"]


def test_convert_directory_in_place_with_force(tmp_path: Path) -> None:
    src_dir = tmp_path / "cassettes"
    (src_dir / "nested").mkdir(parents=True)
    for name in ("a.yaml", "nested/b.yml"):
        c = Cassette()
        c.add_interaction(
            HttpInteraction(
                HttpRequest("GET", f"https://example.com/{name}", {"authorization": ["Bearer x"]}),
                HttpResponse(200),
                "2026-01-01T00:00:00Z",
            )
        )
        c.save(str(src_dir / name))

    main(["convert", str(src_dir), "yaml", "--force"])

    loaded = Cassette.load(str(src_dir / "a.yaml"))
    assert "authorization" not in loaded.interactions[0].request.headers
    # .yml files are rewritten to the target .yaml extension
    assert (src_dir / "nested" / "b.yaml").exists()
    assert not list(src_dir.rglob("*.tmp.*"))


def test_convert_unreadable_file_errors_cleanly(tmp_path: Path) -> None:
    bad = tmp_path / "bad.yaml"
    bad.write_text("interactions:\n- not_a_request: {}\n")
    with pytest.raises(SystemExit, match="1"):
        main(["convert", str(bad), str(tmp_path / "out.toml")])


def test_convert_directory_continues_after_bad_file(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    src_dir = tmp_path / "cassettes"
    src_dir.mkdir()
    (src_dir / "bad.yaml").write_text("interactions:\n- not_a_request: {}\n")
    c = Cassette()
    c.add_interaction(
        HttpInteraction(
            HttpRequest("GET", "https://example.com"),
            HttpResponse(200),
            "2026-01-01T00:00:00Z",
        )
    )
    c.save(str(src_dir / "good.yaml"))

    with pytest.raises(SystemExit, match="1"):
        main(["convert", str(src_dir), "toml"])

    captured = capsys.readouterr()
    assert "bad.yaml" in captured.err
    assert "Converted 1 file(s), failed 1" in captured.out
    assert (src_dir / "good.toml").exists()


def test_convert_no_command() -> None:
    with pytest.raises(SystemExit, match="1"):
        main([])


def test_convert_empty_directory(tmp_path: Path) -> None:
    empty = tmp_path / "empty"
    empty.mkdir()
    with pytest.raises(SystemExit, match="1"):
        main(["convert", str(empty), "toml"])
