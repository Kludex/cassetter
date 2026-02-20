from __future__ import annotations

from vcr_but_better._core import (
    Body,
    HttpInteraction,
    HttpRequest,
    HttpResponse,
    MatchConfig,
    find_match,
)


def _interaction(method: str, uri: str, **kwargs: object) -> HttpInteraction:
    return HttpInteraction(
        request=HttpRequest(method, uri),
        response=HttpResponse(200, body=Body("json", {"matched": f"{method} {uri}"})),
        recorded_at="2026-01-01T00:00:00Z",
    )


class TestFindMatch:
    def test_match_method_and_uri(self) -> None:
        interactions = [
            _interaction("GET", "https://api.example.com/users"),
            _interaction("POST", "https://api.example.com/users"),
            _interaction("GET", "https://api.example.com/items"),
        ]
        config = MatchConfig()  # default: method + uri

        request = HttpRequest("GET", "https://api.example.com/users")
        result = find_match(request, interactions, config)

        assert result is not None
        idx, interaction = result
        assert idx == 0
        assert interaction.request.method == "GET"
        assert interaction.request.uri == "https://api.example.com/users"

    def test_no_match(self) -> None:
        interactions = [_interaction("GET", "https://api.example.com/users")]
        config = MatchConfig()

        request = HttpRequest("DELETE", "https://api.example.com/users")
        result = find_match(request, interactions, config)

        assert result is None

    def test_case_insensitive_method(self) -> None:
        interactions = [_interaction("GET", "https://api.example.com/users")]
        config = MatchConfig()

        request = HttpRequest("get", "https://api.example.com/users")
        result = find_match(request, interactions, config)

        assert result is not None

    def test_match_with_json_body_ignore(self) -> None:
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

        # Different request_id should still match
        request = HttpRequest(
            "POST",
            "https://api.example.com/chat",
            body=Body("json", {"prompt": "hello", "request_id": "xyz789"}),
        )
        result = find_match(request, interactions, config)
        assert result is not None

    def test_match_uri_only(self) -> None:
        interactions = [_interaction("POST", "https://api.example.com/data")]
        config = MatchConfig(match_on=["uri"])

        # Different method should still match
        request = HttpRequest("GET", "https://api.example.com/data")
        result = find_match(request, interactions, config)

        assert result is not None

    def test_multiple_matches_returns_first(self) -> None:
        interactions = [
            _interaction("GET", "https://api.example.com/users"),
            _interaction("GET", "https://api.example.com/users"),
        ]
        config = MatchConfig()

        request = HttpRequest("GET", "https://api.example.com/users")
        result = find_match(request, interactions, config)

        assert result is not None
        assert result[0] == 0
