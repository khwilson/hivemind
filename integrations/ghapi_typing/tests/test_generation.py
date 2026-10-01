from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from generate import extract, generate, prepare  # noqa: E402
from generated.client import AsyncClient, SyncClient, arguments  # noqa: E402
from generated.models import (  # noqa: E402
    ChecksListForRefQuery,
    GitGetRefRequest,
    GitGetRefRoute,
    GitUpdateRefBody,
    GitUpdateRefRequest,
    GitUpdateRefRoute,
)


def reference() -> dict[str, Any]:
    return {
        "ref": "refs/heads/main",
        "node_id": "REF_example",
        "url": "https://api.github.com/repos/example/math/git/refs/heads/main",
        "object": {
            "type": "commit",
            "sha": "a" * 40,
            "url": "https://api.github.com/repos/example/math/git/commits/" + "a" * 40,
        },
    }


def test_schema_closure_and_missing_endpoint() -> None:
    document = json.loads((ROOT / "extracted.json").read_text())
    subset = extract(document, ["git/get-ref"])
    assert set(subset["components"]["schemas"]) == {
        "git-ref",
        "basic-error",
    }
    with pytest.raises(ValueError, match="Unknown operation"):
        extract(document, ["not/an-endpoint"])


def test_requests_preserve_defaults_and_fenced_ref_write() -> None:
    request = GitUpdateRefRequest(
        route=GitUpdateRefRoute(owner="example", repo="math", ref="heads/main"),
        body=GitUpdateRefBody(sha="a" * 40, force=False),
    )
    assert arguments(request)["data"] == {"sha": "a" * 40, "force": False}
    assert arguments(request)["route"]["ref"] == "heads/main"
    assert ChecksListForRefQuery().model_dump(exclude_unset=True) == {}
    with pytest.raises(ValidationError):
        GitUpdateRefBody.model_validate({})
    with pytest.raises(ValidationError):
        ChecksListForRefQuery.model_validate({"filter": "unexpected"})


def test_sync_client_validates_response_without_network() -> None:
    captured: list[tuple[str, str, dict[str, Any]]] = []

    def api(
        path: str, verb: str, *, route: dict[str, Any], query: dict[str, Any], data: Any
    ) -> Any:
        captured.append((path, verb, route))
        return reference()

    result = SyncClient(api).git_get_ref(
        GitGetRefRequest(
            route=GitGetRefRoute(owner="example", repo="math", ref="heads/main")
        )
    )
    assert result.root.object.sha == "a" * 40
    assert captured == [
        (
            "/repos/{owner}/{repo}/git/ref/{ref}",
            "GET",
            {"owner": "example", "repo": "math", "ref": "heads/main"},
        )
    ]


def test_async_client_validates_response_without_network() -> None:
    import asyncio

    async def api(
        path: str, verb: str, *, route: dict[str, Any], query: dict[str, Any], data: Any
    ) -> Any:
        return reference()

    result = asyncio.run(
        AsyncClient(api).git_get_ref(
            GitGetRefRequest(
                route=GitGetRefRoute(owner="example", repo="math", ref="heads/main")
            )
        )
    )
    assert result.root.object.type == "commit"


def test_generated_fixture_refs_aliases_nullable_unions_and_allof(
    tmp_path: Path,
) -> None:
    document = {
        "openapi": "3.0.3",
        "info": {"title": "Offline fixture", "version": "1"},
        "paths": {
            "/fixture/{id}": {
                "get": {
                    "operationId": "fixture/read",
                    "parameters": [
                        {
                            "name": "id",
                            "in": "path",
                            "required": True,
                            "schema": {"type": "integer"},
                        }
                    ],
                    "responses": {
                        "200": {
                            "description": "OK",
                            "content": {
                                "application/json": {
                                    "schema": {"$ref": "#/components/schemas/Response"}
                                }
                            },
                        }
                    },
                }
            }
        },
        "components": {
            "schemas": {
                "Response": {
                    "allOf": [
                        {"$ref": "#/components/schemas/Base"},
                        {
                            "type": "object",
                            "required": ["nullable", "choice", "class"],
                            "properties": {
                                "nullable": {"type": "string", "nullable": True},
                                "choice": {
                                    "oneOf": [{"type": "integer"}, {"type": "string"}]
                                },
                                "class": {"type": "string"},
                                "children": {
                                    "type": "array",
                                    "items": {"$ref": "#/components/schemas/Base"},
                                },
                            },
                        },
                    ]
                },
                "Base": {
                    "type": "object",
                    "required": ["id"],
                    "properties": {"id": {"type": "integer"}},
                },
            }
        },
    }
    generate(document, tmp_path)
    specification = importlib.util.spec_from_file_location(
        "fixture_models", tmp_path / "models.py"
    )
    assert specification is not None and specification.loader is not None
    module = importlib.util.module_from_spec(specification)
    sys.modules["fixture_models"] = module
    specification.loader.exec_module(module)
    response = module.FixtureReadResponse.model_validate(
        {
            "id": 1,
            "nullable": None,
            "choice": "value",
            "class": "alias",
            "children": [{"id": 2}],
        }
    )
    assert response.root.class_ == "alias"
    assert response.root.children[0].id == 2
    assert response.model_dump(by_alias=True)["class"] == "alias"
    with pytest.raises(ValidationError):
        module.FixtureReadResponse.model_validate(
            {"id": 1, "choice": "value", "class": "alias"}
        )


def test_unsupported_inputs_fail_explicitly() -> None:
    document = json.loads((ROOT / "extracted.json").read_text())
    operation = next(iter(document["paths"].values()))["get"]
    operation["parameters"].append(
        {"in": "header", "name": "custom", "schema": {"type": "string"}}
    )
    with pytest.raises(ValueError, match="Unsupported parameter location"):
        prepare(document)
