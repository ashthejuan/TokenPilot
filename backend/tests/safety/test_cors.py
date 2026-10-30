"""CORS is an allowlist of exactly the dashboard origin (PRD §13)."""

from fastapi.testclient import TestClient

ALLOWED = "http://localhost:3000"
DENIED = (
    "http://127.0.0.1:3000",
    "http://localhost:3001",
    "http://localhost",
    "https://localhost:3000",
    "http://evil.example",
    "null",
)
ACAO = "access-control-allow-origin"


def test_cors_only_localhost_3000(client: TestClient, auth_headers: dict[str, str]) -> None:
    allowed = client.options(
        "/api/v1/usage/summary",
        headers={
            "Origin": ALLOWED,
            "Access-Control-Request-Method": "GET",
            "Access-Control-Request-Headers": "authorization",
        },
    )
    assert allowed.status_code == 200
    assert allowed.headers[ACAO] == ALLOWED
    assert "access-control-allow-credentials" not in allowed.headers

    actual = client.get("/api/v1/health", headers={**auth_headers, "Origin": ALLOWED})
    assert actual.headers[ACAO] == ALLOWED

    for origin in DENIED:
        pre = client.options(
            "/api/v1/usage/summary",
            headers={
                "Origin": origin,
                "Access-Control-Request-Method": "GET",
                "Access-Control-Request-Headers": "authorization",
            },
        )
        assert ACAO not in pre.headers, origin
        assert pre.status_code == 400, origin
        simple = client.get("/api/v1/health", headers={**auth_headers, "Origin": origin})
        assert ACAO not in simple.headers, origin

    # No Origin header (CLI, gateway clients, the Next.js server proxy): unchanged.
    assert client.get("/api/v1/health", headers=auth_headers).status_code == 200
