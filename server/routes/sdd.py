from __future__ import annotations

import base64
import io
import json
import os
from pathlib import Path
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from fastapi.responses import Response
import numpy as np
import pydicom
from pydantic import BaseModel
from sqlalchemy import inspect, text
from sqlalchemy.orm import Session

from eyened_orm import Creator, SubTask

from ..db import get_db
from .auth import CurrentUser, get_current_user, is_admin_user, require_admin

router = APIRouter(prefix="/sdd", tags=["sdd"])
TABLE_NAME = "SDDGradingData"
KEY_COLUMNS = [
    "grader",
    "pdb",
    "sdb",
    "bscan",
    "x_start",
    "x_end",
    "width_px",
    "laterality",
    "oct_dcm_path",
    "visit_id",
    "oct_dcm_path_updated",
    "ir_dcm_path",
    "ir_dcm_path_updated",
    "patient_id",
    "eye_id",
]
BASE_REQUIRED_COLUMNS = [
    "grader",
    "pdb",
    "sdb",
    "bscan",
    "x_start",
    "x_end",
    "width_px",
    "laterality",
    "oct_dcm_path",
]
IMAGE_ROOT = Path(os.getenv("EYENED_QNAP_ROOT", "/mnt/qnap-rc-02/Eyened-temp-for-test")) / "images"


class SDDDecision(BaseModel):
    decision: int
    stage: Optional[int] = None
    comment: Optional[str] = None


class SDDAssignment(BaseModel):
    user_id: Optional[int] = None


class SDDSubTaskAssignment(BaseModel):
    subtask_id: Optional[int] = None


def _subtask_column_name(columns: list[str]) -> Optional[str]:
    return next((column for column in ("SubTaskID", "subtask_id", "sub_task_id") if column in columns), None)


def _q(identifier: str) -> str:
    return f"`{identifier.replace('`', '``')}`"


def _table_columns(db: Session) -> list[str]:
    engine = db.get_bind()
    if engine is None:
        raise HTTPException(status_code=500, detail="Database engine unavailable")
    inspector = inspect(engine)
    if TABLE_NAME not in inspector.get_table_names():
        raise HTTPException(status_code=404, detail="SDDGradingData table not found")
    return [column["name"] for column in inspector.get_columns(TABLE_NAME)]


def _ensure_subtask_column(db: Session) -> list[str]:
    columns = _table_columns(db)
    if _subtask_column_name(columns) is not None:
        return columns
    db.execute(text(f"ALTER TABLE {_q(TABLE_NAME)} ADD COLUMN {_q('SubTaskID')} INT NULL"))
    db.commit()
    return _table_columns(db)


def _ensure_result_columns(db: Session) -> list[str]:
    columns = _table_columns(db)
    result_columns = {
        "decision": "INT NULL",
        "stage": "INT NULL",
        "comment": "TEXT NULL",
    }
    for column, definition in result_columns.items():
        if column not in columns:
            db.execute(text(f"ALTER TABLE {_q(TABLE_NAME)} ADD COLUMN {_q(column)} {definition}"))
    db.commit()
    return _table_columns(db)


def _key(row: dict[str, Any]) -> str:
    key_dict = {column: row[column] for column in KEY_COLUMNS if column in row}
    return base64.urlsafe_b64encode(json.dumps(key_dict, default=str, sort_keys=True).encode()).decode()


def _decode_key(value: str) -> dict[str, Any]:
    try:
        padded = value + "=" * (-len(value) % 4)
        decoded = json.loads(base64.urlsafe_b64decode(padded.encode()).decode())
        if isinstance(decoded, dict):
            return decoded
        if isinstance(decoded, list):
            return dict(zip(KEY_COLUMNS[: len(decoded)], decoded))
        raise ValueError
    except (ValueError, TypeError, json.JSONDecodeError, UnicodeDecodeError):
        raise HTTPException(status_code=400, detail="Invalid SDD row key")


def _serialize(row: dict[str, Any]) -> dict[str, Any]:
    result = dict(row)
    result["row_key"] = _key(result)
    result["image_url"] = f"/api/sdd/image/{result['row_key']}" if str(result.get("oct_dcm_path_updated") or result.get("oct_dcm_path") or "").strip() else None
    return result


def _scoped_where(current_user: CurrentUser, db: Session, columns: list[str]) -> tuple[str, dict[str, Any]]:
    if is_admin_user(current_user, db):
        return "", {}
    if "grader" not in columns:
        raise HTTPException(status_code=400, detail="grader column not found in SDDGradingData")
    return f" WHERE {_q('grader')} = :user_id", {"user_id": current_user.id}


def _rows(db: Session, current_user: CurrentUser) -> list[dict[str, Any]]:
    columns = _table_columns(db)
    required = set(BASE_REQUIRED_COLUMNS)
    missing = required.difference(columns)
    if missing:
        raise HTTPException(status_code=400, detail=f"Missing SDD columns: {', '.join(sorted(missing))}")
    where, params = _scoped_where(current_user, db, columns)
    selected = ", ".join(_q(column) for column in columns)
    rows = db.execute(
        text(f"SELECT {selected} FROM {_q(TABLE_NAME)}{where} ORDER BY {_q('pdb')}, {_q('sdb')}, {_q('bscan')}, {_q('x_start')}"),
        params,
    ).mappings().all()
    return [_serialize(dict(row)) for row in rows]


def _assignment_rows(db: Session, limit: int, offset: int) -> tuple[list[str], list[dict[str, Any]], int]:
    columns = _table_columns(db)
    selected = ", ".join(_q(column) for column in columns)
    total = int(
        db.execute(text(f"SELECT COUNT(*) FROM {_q(TABLE_NAME)}")).scalar_one()
    )
    rows = db.execute(
        text(
            f"SELECT {selected} FROM {_q(TABLE_NAME)} "
            f"ORDER BY {_q('pdb')}, {_q('sdb')}, {_q('bscan')}, {_q('x_start')} "
            "LIMIT :limit OFFSET :offset"
        ),
        {"limit": max(1, min(limit, 200)), "offset": max(0, offset)},
    ).mappings().all()
    return columns, [_serialize(dict(row)) for row in rows], total


def _key_where(row_key: str, available_columns: Optional[list[str]] = None) -> tuple[str, dict[str, Any]]:
    values = _decode_key(row_key)
    parts = []
    params = {}
    for column, value in values.items():
        if available_columns is not None and column not in available_columns:
            continue
        parts.append(f"({_q(column)} = :key_{column} OR ({_q(column)} IS NULL AND :key_{column} IS NULL))")
        params[f"key_{column}"] = value
    if not parts:
        raise HTTPException(status_code=400, detail="Invalid SDD row key")
    return " AND ".join(parts), params


def _resolve_oct_path(row: dict[str, Any]) -> Path:
    updated_path = str(row.get("oct_dcm_path_updated") or "").strip()
    paths = [updated_path] if updated_path else [row.get("oct_dcm_path")]
    for raw_value in paths:
        raw_path = str(raw_value or "").strip().replace("\\", "/")
        if not raw_path:
            continue
        source_path = Path(raw_path)
        candidate = (source_path if source_path.is_absolute() else IMAGE_ROOT / raw_path.lstrip("/")).resolve()
        if candidate.is_file():
            return candidate

    basename = Path(str(paths[0] or "").replace("\\", "/")).name
    if basename:
        matches = sorted(IMAGE_ROOT.rglob(basename), key=lambda path: str(path))
        if matches:
            return matches[0].resolve()
    raise HTTPException(status_code=404, detail="SDD OCT DICOM file not found")


@router.get("/records")
async def list_sdd_records(db: Session = Depends(get_db), current_user: CurrentUser = Depends(get_current_user)):
    rows = _rows(db, current_user)
    return {"rows": rows, "total": len(rows)}


@router.patch("/records/{row_key}")
async def update_sdd_record(row_key: str, payload: SDDDecision, db: Session = Depends(get_db), current_user: CurrentUser = Depends(get_current_user)):
    columns = _ensure_result_columns(db)
    update_columns = [column for column in ("decision", "stage", "comment") if column in columns]
    if not update_columns:
        raise HTTPException(status_code=409, detail="SDD grading result columns are not present in SDDGradingData")
    key_sql, params = _key_where(row_key, columns)
    scope_sql, scope_params = _scoped_where(current_user, db, columns)
    params.update(scope_params)
    params.update({"decision": payload.decision, "stage": payload.stage, "comment": payload.comment})
    assignments = ", ".join(f"{_q(column)} = :{column}" for column in update_columns)
    result = db.execute(text(f"UPDATE {_q(TABLE_NAME)} SET {assignments}{scope_sql}{' AND ' if scope_sql else ' WHERE '}{key_sql}"), params)
    if result.rowcount == 0:
        raise HTTPException(status_code=404, detail="SDD row not found or not assigned to you")
    db.commit()
    return {"status": "ok"}


@router.get("/image/{row_key}")
async def get_sdd_image(row_key: str, db: Session = Depends(get_db), current_user: CurrentUser = Depends(get_current_user)):
    columns = _table_columns(db)
    key_sql, params = _key_where(row_key, columns)
    scope_sql, scope_params = _scoped_where(current_user, db, columns)
    params.update(scope_params)
    selected = ", ".join(_q(column) for column in columns)
    row = db.execute(
        text(f"SELECT {selected} FROM {_q(TABLE_NAME)}{scope_sql}{' AND ' if scope_sql else ' WHERE '}{key_sql} LIMIT 1"),
        params,
    ).mappings().first()
    if row is None:
        raise HTTPException(status_code=404, detail="SDD image not found")
    candidate = _resolve_oct_path(dict(row))
    if candidate.suffix.lower() != ".dcm":
        return FileResponse(candidate)

    try:
        dataset = pydicom.dcmread(candidate)
        pixels = np.asarray(dataset.pixel_array)
        if pixels.ndim == 3:
            frame_index = int(row.get("bscan") or 0)
            pixels = pixels[max(0, min(frame_index, pixels.shape[0] - 1))]
        pixels = pixels.astype(np.float32)
        low, high = float(np.nanmin(pixels)), float(np.nanmax(pixels))
        if high <= low:
            pixels = np.zeros_like(pixels, dtype=np.uint8)
        else:
            pixels = ((pixels - low) * (255.0 / (high - low))).clip(0, 255).astype(np.uint8)
        if getattr(dataset, "PhotometricInterpretation", "") == "MONOCHROME1":
            pixels = 255 - pixels

        from PIL import Image

        output = io.BytesIO()
        Image.fromarray(pixels).save(output, format="PNG")
        return Response(content=output.getvalue(), media_type="image/png")
    except Exception as exc:
        raise HTTPException(status_code=422, detail=f"Unable to decode SDD DICOM image: {exc}") from exc


@router.get("/assignment")
async def list_sdd_assignments(limit: int = 100, offset: int = 0, db: Session = Depends(get_db), current_user: CurrentUser = Depends(get_current_user)):
    require_admin(current_user, db)
    columns, rows, total = _assignment_rows(db, limit, offset)

    subtask_column = _subtask_column_name(columns)
    if subtask_column:
        subtask_ids = sorted({int(r[subtask_column]) for r in rows if r.get(subtask_column) not in (None, "")})
        creator_by_subtask_id: dict[int, Optional[int]] = {}
        if subtask_ids:
            subtask_rows = db.query(SubTask).filter(SubTask.SubTaskID.in_(subtask_ids)).all()
            creator_by_subtask_id = {
                int(r.SubTaskID): (int(r.CreatorID) if r.CreatorID is not None else None)
                for r in subtask_rows
            }
        creator_ids = sorted({cid for cid in creator_by_subtask_id.values() if cid is not None})
        usernames: dict[int, str] = {}
        if creator_ids:
            creator_rows = db.query(Creator).filter(Creator.CreatorID.in_(creator_ids)).all()
            usernames = {int(r.CreatorID): str(r.CreatorName) for r in creator_rows}

        for row in rows:
            raw_subtask_id = row.get(subtask_column)
            subtask_id_int = int(raw_subtask_id) if raw_subtask_id not in (None, "") else None
            assignee_user_id = creator_by_subtask_id.get(subtask_id_int) if subtask_id_int is not None else None
            row["subtask_id"] = subtask_id_int
            row["subtask_assignee_user_id"] = assignee_user_id
            row["subtask_assignee_username"] = (
                usernames.get(assignee_user_id) if assignee_user_id is not None else None
            )

    return {"columns": columns, "subtask_column": subtask_column, "rows": rows, "total": total}


@router.patch("/assignment/{row_key}")
async def assign_sdd_record(row_key: str, payload: SDDAssignment, db: Session = Depends(get_db), current_user: CurrentUser = Depends(get_current_user)):
    require_admin(current_user, db)
    columns = _table_columns(db)
    key_sql, params = _key_where(row_key, columns)
    params["user_id"] = payload.user_id
    result = db.execute(text(f"UPDATE {_q(TABLE_NAME)} SET {_q('grader')} = :user_id WHERE {key_sql}"), params)
    if result.rowcount == 0:
        raise HTTPException(status_code=404, detail="SDD row not found")
    db.commit()
    return {"status": "ok"}


@router.patch("/assignment/{row_key}/subtask")
async def assign_sdd_row_subtask(
    row_key: str,
    payload: SDDSubTaskAssignment,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
):
    require_admin(current_user, db)
    columns = _ensure_subtask_column(db)
    subtask_column = _subtask_column_name(columns)
    if subtask_column is None:
        raise HTTPException(status_code=400, detail="SubTaskID column not found in SDDGradingData")

    if payload.subtask_id is not None:
        subtask = db.execute(
            text("SELECT `SubTaskID` FROM `SubTask` WHERE `SubTaskID` = :subtask_id LIMIT 1"),
            {"subtask_id": payload.subtask_id},
        ).mappings().first()
        if subtask is None:
            raise HTTPException(status_code=404, detail="SubTask not found")

    key_sql, params = _key_where(row_key, columns)
    params["subtask_id"] = payload.subtask_id
    result = db.execute(
        text(f"UPDATE {_q(TABLE_NAME)} SET {_q(subtask_column)} = :subtask_id WHERE {key_sql}"),
        params,
    )
    if result.rowcount == 0:
        raise HTTPException(status_code=404, detail="SDD row not found")
    db.commit()
    return {"status": "ok"}


@router.patch("/assignment/subtask/{subtask_id}")
async def assign_sdd_subtask(subtask_id: int, payload: SDDAssignment, db: Session = Depends(get_db), current_user: CurrentUser = Depends(get_current_user)):
    require_admin(current_user, db)
    columns = _ensure_subtask_column(db)
    subtask_column = _subtask_column_name(columns)
    if subtask_column is None:
        raise HTTPException(status_code=400, detail="SubTaskID column not found in SDDGradingData")
    result = db.execute(
        text(f"UPDATE {_q(TABLE_NAME)} SET {_q('grader')} = :user_id WHERE {_q(subtask_column)} = :subtask_id"),
        {"user_id": payload.user_id, "subtask_id": subtask_id},
    )
    db.commit()
    return {"status": "ok", "updated": result.rowcount}