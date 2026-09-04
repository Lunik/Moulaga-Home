"""Local attachment storage under the configured data directory."""

from __future__ import annotations

import hashlib
import re
import secrets
from pathlib import Path

from fastapi import HTTPException, UploadFile

from . import config

MAX_ATTACHMENT_SIZE = 25 * 1024 * 1024


def _safe_filename(filename: str | None) -> str:
    basename = Path(filename or "piece-jointe").name
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "-", basename).strip(".-")
    return (cleaned or "piece-jointe")[:255]


def attachment_path(stored_path: str) -> Path:
    root = config.settings.data_dir.resolve()
    resolved = (root / stored_path).resolve()
    if not resolved.is_relative_to(root):
        raise ValueError("Chemin de piece jointe invalide")
    return resolved


async def store_attachment(upload: UploadFile) -> tuple[str, str, int]:
    payload = await upload.read(MAX_ATTACHMENT_SIZE + 1)
    await upload.close()
    if not payload:
        raise HTTPException(status_code=422, detail="La piece jointe est vide")
    if len(payload) > MAX_ATTACHMENT_SIZE:
        raise HTTPException(
            status_code=413,
            detail="La piece jointe depasse la limite de 25 Mio",
        )

    storage_key = hashlib.sha256(secrets.token_bytes(32) + payload).hexdigest()
    filename = _safe_filename(upload.filename)
    relative = Path("attached") / storage_key[:2] / storage_key[2:4] / storage_key / filename
    destination = attachment_path(relative.as_posix())
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(f".{storage_key}.upload")
    temporary.write_bytes(payload)
    temporary.replace(destination)
    return filename, relative.as_posix(), len(payload)


def remove_attachment(stored_path: str) -> None:
    attachment_path(stored_path).unlink(missing_ok=True)
