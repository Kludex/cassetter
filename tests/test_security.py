from __future__ import annotations

from cassetter._core import (
    Body,
    HttpInteraction,
    HttpRequest,
    HttpResponse,
    SecurityConfig,
    scrub_interaction,
)


def test_security_default_filter_headers() -> None:
    config = SecurityConfig()
    assert "authorization" in config.filter_headers
    assert "cookie" in config.filter_headers
    assert "x-api-key" in config.filter_headers


def test_security_default_filter_query_parameters() -> None:
    config = SecurityConfig()
    assert "api_key" in config.filter_query_parameters
    assert "access_token" in config.filter_query_parameters


def test_security_default_body_scrub_patterns() -> None:
    config = SecurityConfig()
    assert "password" in config.body_scrub_patterns
    assert "access_token" in config.body_scrub_patterns


def test_scrub_headers() -> None:
    interaction = HttpInteraction(
        request=HttpRequest(
            "GET",
            "https://api.example.com/v1",
            {"authorization": ["Bearer secret"], "content-type": ["application/json"]},
        ),
        response=HttpResponse(
            200,
            {"set-cookie": ["session=abc"], "content-type": ["application/json"]},
            Body("json", {"result": "ok"}),
        ),
        recorded_at="2026-01-01T00:00:00Z",
    )
    config = SecurityConfig()
    scrubbed = scrub_interaction(interaction, config)

    assert "authorization" not in scrubbed.request.headers
    assert "content-type" in scrubbed.request.headers
    assert "set-cookie" not in scrubbed.response.headers


def test_scrub_query_params() -> None:
    interaction = HttpInteraction(
        request=HttpRequest(
            "GET",
            "https://api.example.com/v1?api_key=secret&format=json",
        ),
        response=HttpResponse(200),
        recorded_at="2026-01-01T00:00:00Z",
    )
    config = SecurityConfig()
    scrubbed = scrub_interaction(interaction, config)

    assert "secret" not in scrubbed.request.uri
    assert "FILTERED" in scrubbed.request.uri
    assert "format=json" in scrubbed.request.uri


def test_scrub_json_body() -> None:
    interaction = HttpInteraction(
        request=HttpRequest(
            "POST",
            "https://api.example.com/auth",
            body=Body("json", {"username": "alice", "password": "secret123"}),
        ),
        response=HttpResponse(
            200,
            body=Body("json", {"access_token": "tok_abc", "expires_in": 3600}),
        ),
        recorded_at="2026-01-01T00:00:00Z",
    )
    config = SecurityConfig()
    scrubbed = scrub_interaction(interaction, config)

    assert scrubbed.request.body.content["password"] == "[FILTERED]"
    assert scrubbed.request.body.content["username"] == "alice"
    assert scrubbed.response.body.content["access_token"] == "[FILTERED]"
    assert scrubbed.response.body.content["expires_in"] == 3600


def test_scrub_custom_replacement() -> None:
    interaction = HttpInteraction(
        request=HttpRequest(
            "POST",
            "https://api.example.com/auth",
            body=Body("json", {"password": "secret"}),
        ),
        response=HttpResponse(200),
        recorded_at="2026-01-01T00:00:00Z",
    )
    config = SecurityConfig(replacement="***REDACTED***")
    scrubbed = scrub_interaction(interaction, config)

    assert scrubbed.request.body.content["password"] == "***REDACTED***"


def test_scrub_custom_filter_list() -> None:
    interaction = HttpInteraction(
        request=HttpRequest(
            "GET",
            "https://api.example.com/v1",
            {"x-custom-secret": ["my-secret"], "content-type": ["text/plain"]},
        ),
        response=HttpResponse(200),
        recorded_at="2026-01-01T00:00:00Z",
    )
    config = SecurityConfig(
        filter_headers=["x-custom-secret"],
        filter_query_parameters=[],
        body_scrub_patterns=[],
    )
    scrubbed = scrub_interaction(interaction, config)

    assert "x-custom-secret" not in scrubbed.request.headers
    assert "content-type" in scrubbed.request.headers
