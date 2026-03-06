from __future__ import annotations

from cassetter._core import (
    Body,
    HttpInteraction,
    HttpRequest,
    HttpResponse,
    MatchConfig,
    find_match,
)


def _interaction(method: str, uri: str) -> HttpInteraction:
    return HttpInteraction(
        request=HttpRequest(method, uri),
        response=HttpResponse(200, body=Body("json", {"matched": f"{method} {uri}"})),
        recorded_at="2026-01-01T00:00:00Z",
    )


def _no_played(n: int) -> list[bool]:
    return [False] * n


def test_find_match_method_and_uri() -> None:
    interactions = [
        _interaction("GET", "https://api.example.com/users"),
        _interaction("POST", "https://api.example.com/users"),
        _interaction("GET", "https://api.example.com/items"),
    ]
    config = MatchConfig()

    request = HttpRequest("GET", "https://api.example.com/users")
    result = find_match(request, interactions, _no_played(3), config)

    assert result is not None
    idx, interaction = result
    assert idx == 0
    assert interaction.request.method == "GET"
    assert interaction.request.uri == "https://api.example.com/users"


def test_find_match_no_match() -> None:
    interactions = [_interaction("GET", "https://api.example.com/users")]
    config = MatchConfig()

    request = HttpRequest("DELETE", "https://api.example.com/users")
    result = find_match(request, interactions, _no_played(1), config)

    assert result is None


def test_find_match_case_insensitive_method() -> None:
    interactions = [_interaction("GET", "https://api.example.com/users")]
    config = MatchConfig()

    request = HttpRequest("get", "https://api.example.com/users")
    result = find_match(request, interactions, _no_played(1), config)

    assert result is not None


def test_find_match_with_json_body_ignore() -> None:
    interactions = [
        HttpInteraction(
            request=HttpRequest(
                "POST",
                "https://api.example.com/chat",
                body=Body("json", {"prompt": "hello", "request_id": "abc123"}),
            ),
            response=HttpResponse(200, body=Body("json", {"reply": "hi"})),
            recorded_at="2026-01-01T00:00:00Z",
        )
    ]
    config = MatchConfig(
        match_on=["method", "uri", "json_body"],
        ignore_json_paths=["request_id"],
    )

    request = HttpRequest(
        "POST",
        "https://api.example.com/chat",
        body=Body("json", {"prompt": "hello", "request_id": "xyz789"}),
    )
    result = find_match(request, interactions, _no_played(1), config)
    assert result is not None


def test_find_match_uri_only() -> None:
    interactions = [_interaction("POST", "https://api.example.com/data")]
    config = MatchConfig(match_on=["uri"])

    request = HttpRequest("GET", "https://api.example.com/data")
    result = find_match(request, interactions, _no_played(1), config)

    assert result is not None


def test_find_match_prefers_unplayed_interaction() -> None:
    interactions = [
        _interaction("GET", "https://api.example.com/users"),
        _interaction("GET", "https://api.example.com/users"),
    ]
    config = MatchConfig()
    played = [True, False]

    request = HttpRequest("GET", "https://api.example.com/users")
    result = find_match(request, interactions, played, config)

    assert result is not None
    assert result[0] == 1


def test_find_match_falls_back_to_played_interaction() -> None:
    interactions = [
        _interaction("GET", "https://api.example.com/users"),
    ]
    config = MatchConfig()
    played = [True]

    request = HttpRequest("GET", "https://api.example.com/users")
    result = find_match(request, interactions, played, config)

    assert result is not None
    assert result[0] == 0
