# Generated typing for ghapi

This is an isolated prototype for a possible upstream contribution to
[ghapi](https://github.com/AnswerDotAI/ghapi), pinned to ghapi 2.1.4. It generates
endpoint signatures and response types from GitHub's official OpenAPI schemas;
there are no handwritten per-endpoint models. It is not part of Hivemind's broker
runtime, and no upstream pull request has been opened.

## What gets generated

- `generated/raw_api.pyi`: opt-in synchronous and asynchronous ghapi protocols,
  with the SDK's existing endpoint groups/names and keyword parameter types.
- `generated/raw_models.py`: `TypedDict` response shapes for raw JSON/AttrDict
  values. These types support dictionary access, not AttrDict attribute access.
- `generated/models.py`: Pydantic v2 request and response models.
- `generated/client.py`: optional synchronous and asynchronous adapters that
  validate response values into the Pydantic models.

The raw protocols describe ghapi's actual dictionary responses. They do **not**
pretend that ghapi returns Pydantic instances. The optional adapters perform that
conversion explicitly. Both paths are checked with `ty`, including negative tests
for invalid query literals and incorrect response-field types.

## Reproduce and verify

From this directory, install the isolated dependencies and run all checks:

```sh
uv sync --locked
uv run python verify.py
```

`verify.py` runs Ruff, formatting, ty, pytest, and byte-for-byte offline
regeneration comparisons. The committed lockfile pins the generator and its
dependencies. Generated syntax targets Python 3.11; no GitHub credentials or live
API calls are required by verification.

`source.json` pins the official
[GitHub OpenAPI description](https://github.com/github/rest-api-description) to a
commit, API version, full-document SHA256, and endpoint selection. The committed
`extracted.json` contains only those endpoints and their transitive component
closure (about 39 KB, compared with the full 12 MB document). Its SHA256 is also
checked during offline generation.

To reproduce the extraction from the immutable upstream source:

```sh
uv run python generate.py --extract
```

Or provide a downloaded document without using the network:

```sh
uv run python generate.py --extract --source /path/to/api.github.com.2026-03-10.json
```

To cover more endpoints, edit the `operations` list in `source.json`, re-extract,
and review the regenerated changes. `--output DIRECTORY` redirects generated
Python files. This example covers check-run inspection and atomic Git ref reads
and updates, selected for Hivemind. It does not claim full API coverage.

## Using the raw signatures

```python
from typing import TYPE_CHECKING, cast
from ghapi.core import GhApi

if TYPE_CHECKING:
    from generated.raw_api import SyncGhApi

api = cast("SyncGhApi", GhApi(owner="example", repo="math", sync=True))
result = api.git.get_ref(ref="heads/main")
sha: str = result["object"]["sha"]
```

`raw_api.py` is a static-only placeholder: its protocol names are available to
type checkers through the matching `.pyi`, and must be imported under
`TYPE_CHECKING`. The cast marks the boundary between ghapi's dynamic generation
and these checked signatures. Use `AsyncGhApi` with the default asynchronous
client and `await` its endpoint calls.

Endpoint arguments are optional in the raw protocol because constructor-bound
ghapi defaults can supply them. The protocol does not prove those defaults exist
or enforce a required argument that might be bound elsewhere. For explicit,
validated inputs, use the request models and optional adapter instead:

```python
from typing import cast
from ghapi.core import GhApi
from generated.client import SyncAPI, SyncClient
from generated.models import GitGetRefRequest, GitGetRefRoute

client = SyncClient(cast(SyncAPI, GhApi(sync=True)))
result = client.git_get_ref(
    GitGetRefRequest(
        route=GitGetRefRoute(owner="example", repo="math", ref="heads/main")
    )
)
sha: str = result.root.object.sha
```

Adapters dump requests using wire aliases and `exclude_unset=True`, preserving
omitted parameters, explicit values, and `force=False`. Choose the matching
synchronous or asynchronous SDK mode; these casts do not validate SDK mode.
The adapter relies on ghapi for HTTP behavior, and adds no pagination policy.

## Schema handling and limits

Model generation uses
[datamodel-code-generator](https://datamodel-code-generator.koxudaxi.dev/), rather
than a new handwritten schema-to-Python implementation. Fixture tests exercise
local references, required nullable fields, reserved-name aliases, arrays,
literal enums, unions, and `allOf` inheritance. Response formats and constraints
are represented by Pydantic where the generator supports them. Pydantic's usual
coercion applies; these models are not a security or mathematical-proof validator.

This prototype supports local component references, path/query parameters, JSON
request bodies, and JSON or empty successful responses. Unsupported external
references, header/cookie parameters, non-JSON content, missing operations, and
operation-name collisions fail explicitly. Raw signatures additionally require
object request bodies. Multiple successful response schemas form a union; the
adapter does not dispatch validation by HTTP status. Error responses still follow
ghapi's error behavior.

Important remaining work before claiming complete schema fidelity:

- Optional non-nullable Pydantic fields without defaults can become `T | None =
  None` in the model generator. Omission and explicit null are not fully separated
  in those generated models. Required nullable fields are tested correctly.
- `readOnly`/`writeOnly` remain upstream schema annotations. Separate request and
  response projections for reused component schemas are not implemented here.
- JSON Schema/OpenAPI constructs beyond the tested subset (discriminators,
  complex mixed additional properties, recursive unions, advanced constraints)
  need wider conformance fixtures and endpoint coverage before acceptance.
- Raw signatures intentionally omit dynamic SDK escape hatches such as
  `headers_`, `query_`, `body_`, positional calls, and transport/convenience
  methods. The prototype does not type GraphQL or dynamic AttrDict attributes.
- The official schema and ghapi's compressed metadata can evolve independently.
  Upstream integration should pin both and check endpoint naming/availability in
  release CI. API/schema correctness is not established by type checking alone.

## Possible upstream PR

The initial contribution could add a pinned schema acquisition/extraction step,
generated raw endpoint signatures and JSON response shapes, regeneration checks,
and type-checker consumer fixtures to ghapi's existing generation pipeline.
These fit the current runtime without changing return values. ghapi's compressed
metadata contains parameter names and coarse types, but not the complete response
schemas needed to generate these models; the official source supplies that data.

Pydantic models and validating adapters are a separate, optional proposal, ideally
an extra dependency rather than an imposed runtime behavior change. Before an
upstream PR, agree the supported ghapi/Python versions, full endpoint naming rules,
SDK defaults and mode typing, licensing/package layout, model-generation policy,
and the nullability/read-write gaps above with maintainers. This folder is a
reviewable starting point, not an upstream-ready full client replacement.

The extracted official schema is covered by GitHub's MIT license, reproduced in
`GITHUB_SCHEMA_LICENSE.md` with the upstream copyright notice. Generated model
files derive from that schema; retain this notice when distributing the example.
