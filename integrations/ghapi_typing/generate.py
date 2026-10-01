"""Generate Pydantic models and typed adapters from official GitHub OpenAPI."""

from __future__ import annotations

import argparse
import hashlib
import json
import keyword
import re
import subprocess
import sys
import tempfile
import urllib.request
from copy import deepcopy
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent
METHODS = {"get", "put", "post", "patch", "delete", "head", "options"}


def identifier(value: str) -> str:
    result = re.sub(r"\W", "_", value)
    if not result or result[0].isdigit() or keyword.iskeyword(result):
        result = f"field_{result}"
    return result


def class_name(value: str) -> str:
    return "".join(piece.title() for piece in re.split(r"[^a-zA-Z0-9]", value))


def references(value: Any) -> set[str]:
    if isinstance(value, dict):
        result = {value["$ref"]} if "$ref" in value else set()
        return result | set().union(*(references(v) for v in value.values()))
    if isinstance(value, list):
        return set().union(*(references(v) for v in value))
    return set()


def resolve(document: dict[str, Any], value: dict[str, Any]) -> dict[str, Any]:
    seen: set[str] = set()
    while "$ref" in value:
        reference = value["$ref"]
        if not reference.startswith("#/") or reference in seen:
            raise ValueError(f"Unsupported external or cyclic reference: {reference}")
        seen.add(reference)
        value = document
        for piece in reference[2:].split("/"):
            value = value[piece.replace("~1", "/").replace("~0", "~")]
    return value


def extract(document: dict[str, Any], operation_ids: list[str]) -> dict[str, Any]:
    """Copy selected operations and their complete local component closure."""
    selected: dict[str, Any] = {}
    found: set[str] = set()
    for path, item in document["paths"].items():
        for method, operation in item.items():
            if method in METHODS and operation.get("operationId") in operation_ids:
                found.add(operation["operationId"])
                selected.setdefault(path, {})[method] = deepcopy(operation)
                if "parameters" in item:
                    selected[path]["parameters"] = deepcopy(item["parameters"])
    if missing := set(operation_ids) - found:
        raise ValueError(f"Unknown operation IDs: {sorted(missing)}")
    result = {
        "openapi": document["openapi"],
        "info": document["info"],
        "paths": selected,
        "components": {},
    }
    pending = references(selected)
    included: set[str] = set()
    while pending:
        reference = pending.pop()
        if reference in included:
            continue
        if not reference.startswith("#/components/"):
            raise ValueError(f"Unsupported reference: {reference}")
        _, _, section, name = reference.split("/", 3)
        component = resolve(document, {"$ref": reference})
        result["components"].setdefault(section, {})[name] = deepcopy(component)
        included.add(reference)
        pending |= references(component) - included
    return result


def prepare(document: dict[str, Any]) -> tuple[dict[str, Any], list[dict[str, str]]]:
    """Add schema-derived request/response roots; retain explicit nullability."""
    prepared = deepcopy(document)
    schemas = prepared.setdefault("components", {}).setdefault("schemas", {})
    methods: list[dict[str, str]] = []
    names: set[str] = set()
    for path, item in sorted(document["paths"].items()):
        for verb, operation in sorted(item.items()):
            if verb not in METHODS:
                continue
            operation_id = operation["operationId"]
            name = identifier(operation_id)
            if name in names:
                raise ValueError(f"Python operation name collision: {name}")
            names.add(name)
            prefix = class_name(operation_id)
            pieces: dict[str, dict[str, Any]] = {
                "route": {"type": "object", "properties": {}, "required": []},
                "query": {"type": "object", "properties": {}, "required": []},
            }
            parameters: dict[tuple[str, str], dict[str, Any]] = {}
            for value in item.get("parameters", []) + operation.get("parameters", []):
                parameter = resolve(document, value)
                parameters[(parameter["in"], parameter["name"])] = parameter
            for parameter in parameters.values():
                location = {"path": "route", "query": "query"}.get(parameter["in"])
                if location is None:
                    raise ValueError(
                        f"Unsupported parameter location: {parameter['in']}"
                    )
                schema = deepcopy(parameter["schema"])
                pieces[location]["properties"][parameter["name"]] = schema
                if parameter.get("required"):
                    pieces[location]["required"].append(parameter["name"])
            body_required = False
            if "requestBody" in operation:
                body = resolve(document, operation["requestBody"])
                if "application/json" not in body["content"]:
                    raise ValueError(f"Non-JSON request unsupported: {operation_id}")
                pieces["body"] = deepcopy(body["content"]["application/json"]["schema"])
                body_required = body.get("required", False)
            properties = {}
            required = []
            for piece, schema in pieces.items():
                if piece == "query" and not schema.get("properties"):
                    continue
                model = f"{prefix}{piece.title()}"
                schemas[model] = schema
                properties[piece] = {"$ref": f"#/components/schemas/{model}"}
                if piece == "route" or (piece == "body" and body_required):
                    required.append(piece)
            request_name, response_name = f"{prefix}Request", f"{prefix}Response"
            schemas[request_name] = {
                "type": "object",
                "properties": properties,
                "required": required,
            }
            success = [
                resolve(document, response)
                for code, response in sorted(operation["responses"].items())
                if code.startswith("2")
            ]
            response_schemas = []
            for response in success:
                content = response.get("content", {})
                if not content:
                    response_schemas.append({"type": "null"})
                elif "application/json" in content:
                    response_schemas.append(content["application/json"]["schema"])
                else:
                    raise ValueError(f"Non-JSON response unsupported: {operation_id}")
            if not response_schemas:
                raise ValueError(f"No successful response schema: {operation_id}")
            schemas[response_name] = (
                response_schemas[0]
                if len(response_schemas) == 1
                else {"anyOf": response_schemas}
            )
            methods.append(
                {
                    "name": name,
                    "request": request_name,
                    "response": response_name,
                    "path": path,
                    "verb": verb.upper(),
                }
            )
    return prepared, methods


def adapter_source(methods: list[dict[str, str]]) -> str:
    imports = sorted({m[k] for m in methods for k in ("request", "response")})
    source = """# Generated by generate.py; do not edit.
from __future__ import annotations

from collections.abc import Awaitable
from typing import Any, Protocol

from .models import (
"""
    source += "".join(f"    {name},\n" for name in imports) + ")\n\n"
    source += """class SyncAPI(Protocol):
    def __call__(self, path: str, verb: str, *, route: dict[str, Any],
                 query: dict[str, Any], data: Any) -> Any: ...


class AsyncAPI(Protocol):
    def __call__(self, path: str, verb: str, *, route: dict[str, Any],
                 query: dict[str, Any], data: Any) -> Awaitable[Any]: ...


def arguments(request: Any) -> dict[str, Any]:
    values = request.model_dump(mode="json", by_alias=True, exclude_unset=True)
    return {"route": values.get("route", {}), "query": values.get("query", {}),
            "data": values.get("body")}

"""
    for asynchronous in (False, True):
        cls, protocol = (
            ("AsyncClient", "AsyncAPI") if asynchronous else ("SyncClient", "SyncAPI")
        )
        source += f"class {cls}:\n    def __init__(self, api: {protocol}) -> None:\n        self.api = api\n\n"
        for method in methods:
            prefix = "async " if asynchronous else ""
            await_prefix = "await " if asynchronous else ""
            source += (
                f"    {prefix}def {method['name']}(self, request: {method['request']})"
                f" -> {method['response']}:\n"
                f"        raw = {await_prefix}self.api({method['path']!r}, {method['verb']!r}, **arguments(request))\n"
                f"        return {method['response']}.model_validate(raw)\n\n"
            )
    return source


def schema_type(schema: dict[str, Any]) -> str:
    if "$ref" in schema:
        value = "raw_models." + class_name(schema["$ref"].rsplit("/", 1)[1])
    elif "enum" in schema:
        value = "Literal[" + ", ".join(repr(v) for v in schema["enum"]) + "]"
    elif "oneOf" in schema or "anyOf" in schema:
        value = " | ".join(
            schema_type(v) for v in schema.get("oneOf", schema.get("anyOf", []))
        )
    elif schema.get("type") == "array":
        value = f"list[{schema_type(schema['items'])}]"
    else:
        value = {
            "string": "str",
            "integer": "int",
            "number": "float",
            "boolean": "bool",
            "null": "None",
        }.get(schema.get("type"), "dict[str, Any]")
    return value + " | None" if schema.get("nullable") and value != "None" else value


def raw_stub_source(document: dict[str, Any], methods: list[dict[str, str]]) -> str:
    """Opt-in protocol stubs; raw SDK responses stay dictionaries, not models."""
    groups: dict[str, list[tuple[dict[str, str], dict[str, Any], dict[str, Any]]]] = {}
    for method in methods:
        item = document["paths"][method["path"]]
        operation = item[method["verb"].lower()]
        group, _ = operation["operationId"].split("/", 1)
        groups.setdefault(identifier(group), []).append((method, item, operation))
    source = "# Generated by generate.py; do not edit.\nfrom collections.abc import Awaitable\nfrom typing import Any, Literal, Protocol\nfrom . import raw_models\n\n"
    for asynchronous in (False, True):
        prefix = "Async" if asynchronous else "Sync"
        for group, operations in sorted(groups.items()):
            source += f"class {prefix}{class_name(group)}(Protocol):\n"
            for method, item, operation in operations:
                parameters: dict[str, str] = {}
                for raw in item.get("parameters", []) + operation.get("parameters", []):
                    parameter = resolve(document, raw)
                    parameters[identifier(parameter["name"])] = schema_type(
                        parameter["schema"]
                    )
                if "requestBody" in operation:
                    body = resolve(document, operation["requestBody"])
                    schema = resolve(
                        document, body["content"]["application/json"]["schema"]
                    )
                    if schema.get("type") != "object":
                        raise ValueError(
                            "Raw signatures currently require object request bodies"
                        )
                    parameters.update(
                        {
                            identifier(name): schema_type(value)
                            for name, value in sorted(
                                schema.get("properties", {}).items()
                            )
                        }
                    )
                # Constructor defaults can satisfy parameters; callers may omit them.
                signature = ", ".join(
                    f"{name}: {value} = ..." for name, value in parameters.items()
                )
                response = f"raw_models.{method['response']}"
                if asynchronous:
                    response = f"Awaitable[{response}]"
                name = identifier(operation["operationId"].split("/", 1)[1])
                source += f"    def {name}(self, *, {signature}) -> {response}: ...\n"
            source += "\n"
        source += f"class {prefix}GhApi(Protocol):\n"
        for group in sorted(groups):
            source += f"    {group}: {prefix}{class_name(group)}\n"
        source += "\n"
    return source


def generate(document: dict[str, Any], output: Path) -> None:
    prepared, methods = prepare(document)
    output.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as directory:
        source = Path(directory) / "openapi.json"
        source.write_text(json.dumps(prepared, sort_keys=True))
        subprocess.run(
            [
                sys.executable,
                "-m",
                "datamodel_code_generator",
                "--ignore-pyproject",
                "--input",
                str(source),
                "--input-file-type",
                "openapi",
                "--output",
                str(output / "models.py"),
                "--output-model-type",
                "pydantic_v2.BaseModel",
                "--target-python-version",
                "3.11",
                "--use-union-operator",
                "--enum-field-as-literal",
                "all",
                "--strict-nullable",
                "--field-constraints",
                "--use-standard-collections",
                "--disable-timestamp",
                "--disable-appending-item-suffix",
                "--no-allow-remote-refs",
                "--formatters",
                "builtin",
            ],
            check=True,
        )
        subprocess.run(
            [
                sys.executable,
                "-m",
                "datamodel_code_generator",
                "--ignore-pyproject",
                "--input",
                str(source),
                "--input-file-type",
                "openapi",
                "--output",
                str(output / "raw_models.py"),
                "--output-model-type",
                "typing.TypedDict",
                "--target-python-version",
                "3.11",
                "--use-union-operator",
                "--enum-field-as-literal",
                "all",
                "--strict-nullable",
                "--use-standard-collections",
                "--disable-timestamp",
                "--no-allow-remote-refs",
                "--formatters",
                "builtin",
            ],
            check=True,
        )
    (output / "client.py").write_text(adapter_source(methods))
    (output / "raw_api.pyi").write_text(raw_stub_source(document, methods))
    (output / "raw_api.py").write_text(
        '"""Static-only ghapi protocols; see the matching generated .pyi."""\n'
    )
    subprocess.run(
        [
            sys.executable,
            "-m",
            "ruff",
            "check",
            "--config",
            str(ROOT / "pyproject.toml"),
            "--fix",
            str(output),
        ],
        check=True,
    )
    subprocess.run(
        [
            sys.executable,
            "-m",
            "ruff",
            "format",
            "--config",
            str(ROOT / "pyproject.toml"),
            str(output),
        ],
        check=True,
    )
    # datamodel-code-generator embeds input filenames; avoid a temporary directory.
    for name in ("models.py", "raw_models.py"):
        models = output / name
        models.write_text(
            re.sub(
                r"#   filename:.*", "#   filename: extracted.json", models.read_text()
            )
        )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--source", type=Path, help="Official full OpenAPI JSON; no network"
    )
    parser.add_argument(
        "--extract", action="store_true", help="Refresh hash-verified closure"
    )
    parser.add_argument("--output", type=Path, default=ROOT / "generated")
    args = parser.parse_args()
    manifest = json.loads((ROOT / "source.json").read_text())
    if args.extract:
        if args.source:
            raw = args.source.read_bytes()
        else:
            with urllib.request.urlopen(manifest["url"], timeout=60) as response:
                raw = response.read()
        if hashlib.sha256(raw).hexdigest() != manifest["sha256"]:
            raise ValueError("Source SHA256 mismatch; refusing to generate")
        document = extract(json.loads(raw), manifest["operations"])
        closure = (json.dumps(document, indent=2, sort_keys=True) + "\n").encode()
        (ROOT / "extracted.json").write_bytes(closure)
        manifest["extracted_sha256"] = hashlib.sha256(closure).hexdigest()
        (ROOT / "source.json").write_text(json.dumps(manifest, indent=2) + "\n")
    else:
        closure = (ROOT / "extracted.json").read_bytes()
        if hashlib.sha256(closure).hexdigest() != manifest["extracted_sha256"]:
            raise ValueError("Extracted schema SHA256 mismatch")
        document = json.loads(closure)
    generate(document, args.output)


if __name__ == "__main__":
    main()
