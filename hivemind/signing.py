import base64
import hashlib
import json
import os
from pathlib import Path
from typing import Any

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)

from .models import Envelope, Payload, Settings


def canonical(value: Any) -> bytes:
    def validate(node: Any) -> None:
        if isinstance(node, dict):
            if not all(isinstance(key, str) for key in node):
                raise ValueError("JSON keys must be strings")
            for child in node.values():
                validate(child)
        elif isinstance(node, list):
            for child in node:
                validate(child)
        elif node is not None and type(node) not in (str, int, bool):
            raise ValueError(
                "Signed requests allow strings, integers, booleans, arrays, objects, and null only"
            )

    validate(value)
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False
    ).encode()


def key_id(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()[:16]


def generate(path: Path) -> dict[str, str]:
    key = Ed25519PrivateKey.generate()
    raw = key.public_key().public_bytes(
        serialization.Encoding.Raw, serialization.PublicFormat.Raw
    )
    pem = key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    )
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "wb") as file:
        file.write(pem)
    return {
        "id": key_id(raw),
        "public_key": base64.b64encode(raw).decode(),
        "private_key": str(path),
    }


def sign(payload: Payload, path: Path) -> Envelope:
    if path.stat().st_mode & 0o077:
        raise ValueError("Private signing key must have mode 0600")
    key = serialization.load_pem_private_key(path.read_bytes(), password=None)
    if not isinstance(key, Ed25519PrivateKey):
        raise ValueError("Use an Ed25519 private key")
    raw = key.public_key().public_bytes(
        serialization.Encoding.Raw, serialization.PublicFormat.Raw
    )
    payload.key_id = key_id(raw)
    signature = key.sign(canonical(payload.model_dump()))
    return Envelope(payload=payload, signature=base64.b64encode(signature).decode())


def authorize(envelope: Envelope, github_id: int, settings: Settings, now: int) -> str:
    payload = envelope.payload
    if payload.hub.lower() != settings.hub or payload.project not in {
        p.id for p in settings.projects
    }:
        raise ValueError("Request targets an unauthorized hub or project")
    if (
        payload.issued_at > now + 120
        or payload.expires_at <= now
        or not 0 < payload.expires_at - payload.issued_at <= 86400
    ):
        raise ValueError("Request expired or has invalid timestamps")
    canonical(payload.model_dump())
    if payload.key_id == f"github:{github_id}" and github_id in settings.maintainers:
        if payload.action not in ("add", "edit", "cancel", "prioritize", "note"):
            raise ValueError(
                "Human requests may edit the queue; agents must sign work claims"
            )
        return f"github:{github_id}"
    agent = next((a for a in settings.agents if a.id == payload.key_id), None)
    if (
        agent is None
        or agent.revoked
        or agent.github_id != github_id
        or payload.project not in agent.projects
        or payload.action not in agent.actions
    ):
        raise ValueError(
            "Agent key, GitHub author, project, or action is not authorized"
        )
    try:
        raw = base64.b64decode(agent.public_key, validate=True)
        if key_id(raw) != agent.id:
            raise ValueError("Registered key ID does not match its public key")
        key = Ed25519PublicKey.from_public_bytes(raw)
        key.verify(
            base64.b64decode(envelope.signature, validate=True),
            canonical(payload.model_dump()),
        )
    except (InvalidSignature, ValueError) as exc:
        raise ValueError("Invalid agent signature") from exc
    return agent.id
