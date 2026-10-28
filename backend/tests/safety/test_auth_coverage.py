import re

from fastapi import FastAPI
from fastapi.testclient import TestClient

_PATH_PARAM = re.compile(r"\{[^}]+\}")


def test_every_api_v1_route_requires_token(app: FastAPI) -> None:
    """Deny-by-default rail: a new router cannot forget the auth dependency."""
    documented_paths = app.openapi()["paths"]
    api_paths = {
        path: operations
        for path, operations in documented_paths.items()
        if path.startswith("/api/v1")
    }
    assert api_paths

    with TestClient(app) as client:
        for path, operations in api_paths.items():
            concrete = _PATH_PARAM.sub("x", path)
            for method in operations:
                response = client.request(method.upper(), concrete)
                assert response.status_code == 401, f"{method.upper()} {path} was not guarded"
