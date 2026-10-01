"""Exercise ghapi's real sync transport without making network requests."""

import json

import httpx2
import pytest

from hivemind.github import ApiError, GitHub


@pytest.fixture
def api(monkeypatch):
    monkeypatch.setenv("GITHUB_JWT_TOKEN", "ambient-jwt")
    monkeypatch.setenv("GH_HOST", "https://untrusted.example")
    return GitHub("scoped-token")


def serve(api, handler):
    api.api.transport.client = httpx2.Client(transport=httpx2.MockTransport(handler))
    return api.api.transport.client


def test_request_headers_query_json_and_empty_response(api):
    requests = []

    def handler(request):
        requests.append(request)
        assert request.url.host == "api.github.com"
        assert request.headers["authorization"] == "Bearer scoped-token"
        assert request.headers["x-github-api-version"] == "2026-03-10"
        if request.method == "GET":
            assert request.url.params["ref"] == "feature/test"
            return httpx2.Response(200, json={"sha": "a" * 40})
        assert json.loads(request.content) == {"sha": "b" * 40, "force": False}
        return httpx2.Response(204)

    with serve(api, handler):
        assert (
            api.get("/repos/owner/math/git/ref/heads/main?ref=feature%2Ftest")["sha"]
            == "a" * 40
        )
        assert (
            api.request(
                "/repos/owner/math/git/refs/heads/hivemind-state",
                "PATCH",
                {"sha": "b" * 40, "force": False},
            )
            is None
        )
    assert len(requests) == 2


@pytest.mark.parametrize("status", [403, 404, 409, 422, 429, 503])
def test_errors_keep_status_and_do_not_replay_writes(api, status):
    requests = []

    def handler(request):
        requests.append(request)
        return httpx2.Response(status, json={"message": "Rejected"})

    with serve(api, handler):
        with pytest.raises(ApiError, match="Rejected") as raised:
            api.request(
                "/repos/owner/math/git/refs/heads/hivemind-state",
                "PATCH",
                {"force": False},
            )
    assert raised.value.status == status
    assert len(requests) == 1


def test_connection_failure_does_not_replay_issue_creation(api):
    requests = []

    def handler(request):
        requests.append(request)
        raise httpx2.ConnectError("connection unavailable", request=request)

    with serve(api, handler):
        with pytest.raises(ApiError) as raised:
            api.request("/repos/owner/math/issues", "POST", {"title": "request"})
    assert raised.value.status == 503
    assert len(requests) == 1


def test_pagination_and_graphql_errors(api):
    pages = []

    def handler(request):
        if request.url.path == "/graphql":
            assert json.loads(request.content)["variables"] == {"owner": "owner"}
            return httpx2.Response(
                200, json={"errors": [{"message": "Not authorized"}]}
            )
        page = int(request.url.params["page"])
        pages.append(page)
        assert request.url.params["filter"] == "latest"
        return httpx2.Response(
            200, json={"check_runs": [{"id": page}] * (100 if page == 1 else 1)}
        )

    with serve(api, handler):
        assert (
            len(
                api.pages(
                    "/repos/owner/math/commits/head/check-runs?filter=latest",
                    "check_runs",
                )
            )
            == 101
        )
        with pytest.raises(ValueError, match="Not authorized"):
            api.graphql("query { viewer { login } }", {"owner": "owner"})
    assert pages == [1, 2]


def test_anonymous_token_does_not_use_ambient_credentials(monkeypatch):
    monkeypatch.setenv("GITHUB_TOKEN", "ambient-token")
    monkeypatch.setenv("GITHUB_JWT_TOKEN", "ambient-jwt")
    api = GitHub("")

    def handler(request):
        assert "authorization" not in request.headers
        return httpx2.Response(200, json={"id": 1})

    with serve(api, handler):
        assert api.get("/user")["id"] == 1
