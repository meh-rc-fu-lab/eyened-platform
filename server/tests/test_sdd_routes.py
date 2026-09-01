"""Integration tests for the SDD management routes (server/routes/sdd.py).

Covers the two management-page requirements:
1. GET /sdd/assignment lists every row stored in SDDGradingData.
2. PATCH /sdd/assignment/{row_key}/subtask assigns a SubTaskID to a single row
   (plus the bulk PATCH /sdd/assignment/subtask/{subtask_id} helper).
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.orm import sessionmaker

server_root = Path(__file__).resolve().parents[1]
orm_root = server_root.parent / "orm"
for path in (str(orm_root), str(server_root)):
    if path not in sys.path:
        sys.path.insert(0, path)

from eyened_orm.utils.sqlite_testdb import create_sqlite_memory_engine  # noqa: E402
from eyened_orm.utils.factories import make_creator  # noqa: E402
from server.db import get_db  # noqa: E402
from server.routes.auth import CurrentUser, get_current_user  # noqa: E402
from server.routes.sdd import BASE_REQUIRED_COLUMNS, KEY_COLUMNS, router as sdd_router  # noqa: E402


@pytest.fixture()
def db_session():
    engine = create_sqlite_memory_engine()
    with engine.begin() as conn:
        conn.execute(
            text(
                """
                CREATE TABLE SDDGradingData (
                    grader INTEGER,
                    pdb TEXT,
                    sdb TEXT,
                    bscan INTEGER,
                    x_start INTEGER,
                    x_end INTEGER,
                    width_px INTEGER,
                    laterality TEXT,
                    oct_dcm_path TEXT,
                    oct_dcm_path_updated TEXT,
                    SubTaskID INTEGER
                )
                """
            )
        )
    factory = sessionmaker(bind=engine, future=True, expire_on_commit=False)
    with factory() as session:
        yield session


@pytest.fixture()
def admin_user(db_session):
    creator = make_creator(db_session, "admin")
    creator.Role = 1
    grader = make_creator(db_session, "grader-user")
    db_session.commit()
    return creator, grader


@pytest.fixture()
def client(db_session, admin_user):
    app = FastAPI()
    app.include_router(sdd_router, prefix="/api")
    admin, _grader = admin_user

    def override_db():
        yield db_session

    def override_user():
        return CurrentUser(creator_id=admin.CreatorID, username="root", role="admin")

    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[get_current_user] = override_user
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


def _seed_rows(db_session, count=3, subtask_id=None):
    for index in range(count):
        db_session.execute(
            text(
                "INSERT INTO SDDGradingData "
                "(grader, pdb, sdb, bscan, x_start, x_end, width_px, laterality, oct_dcm_path, SubTaskID) "
                "VALUES (:grader, :pdb, :sdb, :bscan, :x_start, :x_end, :width_px, :laterality, :path, :subtask)"
            ),
            {
                "grader": None,
                "pdb": f"pdb-{index}",
                "sdb": "sdb-1",
                "bscan": index,
                "x_start": index * 10,
                "x_end": index * 10 + 5,
                "width_px": 200,
                "laterality": "R",
                "path": f"img/{index}.dcm",
                "subtask": subtask_id,
            },
        )
    db_session.commit()


def _row_keys(client):
    payload = client.get("/api/sdd/assignment").json()
    return [row["row_key"] for row in payload["rows"]]


def test_assignment_lists_all_sdd_grading_data_rows(client, db_session):
    _seed_rows(db_session, count=4)
    response = client.get("/api/sdd/assignment")
    assert response.status_code == 200
    payload = response.json()

    assert payload["total"] == 4
    assert len(payload["rows"]) == 4
    assert payload["subtask_column"] == "SubTaskID"
    for column in BASE_REQUIRED_COLUMNS:
        assert column in payload["columns"]
    for row in payload["rows"]:
        assert "row_key" in row
        assert row["subtask_id"] is None


def _make_sdd_subtask(db_session, creator_id):
    from eyened_orm.task import SubTask, SubTaskState, Task, TaskDefinition, TaskState

    definition = TaskDefinition(TaskDefinitionName="SDD grading")
    task = Task(TaskName="SDD", TaskDefinition=definition, TaskState=TaskState.NotStarted)
    subtask = SubTask(Task=task, CreatorID=creator_id, TaskState=SubTaskState.NotStarted)
    db_session.add_all([definition, task, subtask])
    db_session.commit()
    return subtask


def test_row_subtask_assignment_sets_subtask_id(client, db_session, admin_user):
    _creator, grader = admin_user
    subtask = _make_sdd_subtask(db_session, grader.CreatorID)

    _seed_rows(db_session, count=2)
    row_key = _row_keys(client)[0]

    response = client.patch(
        f"/api/sdd/assignment/{row_key}/subtask",
        json={"subtask_id": subtask.SubTaskID},
    )
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}

    stored = db_session.execute(text("SELECT SubTaskID FROM SDDGradingData LIMIT 1")).scalar()
    assert stored == subtask.SubTaskID

    payload = client.get("/api/sdd/assignment").json()
    updated = next(row for row in payload["rows"] if row["row_key"] == row_key)
    assert updated["subtask_id"] == subtask.SubTaskID
    assert updated["subtask_assignee_user_id"] == grader.CreatorID
    assert updated["subtask_assignee_username"] == "grader-user"


def test_row_subtask_assignment_clears_subtask_id(client, db_session):
    _seed_rows(db_session, count=1, subtask_id=42)
    row_key = _row_keys(client)[0]

    response = client.patch(
        f"/api/sdd/assignment/{row_key}/subtask",
        json={"subtask_id": None},
    )
    assert response.status_code == 200
    stored = db_session.execute(text("SELECT SubTaskID FROM SDDGradingData LIMIT 1")).scalar()
    assert stored is None


def test_row_subtask_assignment_rejects_unknown_subtask(client, db_session):
    _seed_rows(db_session, count=1)
    row_key = _row_keys(client)[0]
    response = client.patch(
        f"/api/sdd/assignment/{row_key}/subtask",
        json={"subtask_id": 999_999},
    )
    assert response.status_code == 404


def test_bulk_subtask_assignment_updates_grader(client, db_session, admin_user):
    _creator, grader = admin_user
    _seed_rows(db_session, count=3, subtask_id=7)
    _seed_rows(db_session, count=1, subtask_id=8)

    response = client.patch(
        "/api/sdd/assignment/subtask/7",
        json={"user_id": grader.CreatorID},
    )
    assert response.status_code == 200
    assert response.json()["updated"] == 3

    assigned = db_session.execute(
        text("SELECT grader FROM SDDGradingData WHERE SubTaskID = 7")
    ).scalars().all()
    assert assigned == [grader.CreatorID] * 3


def test_row_grader_assignment(client, db_session, admin_user):
    _creator, grader = admin_user
    _seed_rows(db_session, count=1)
    row_key = _row_keys(client)[0]

    response = client.patch(
        f"/api/sdd/assignment/{row_key}",
        json={"user_id": grader.CreatorID},
    )
    assert response.status_code == 200
    stored = db_session.execute(text("SELECT grader FROM SDDGradingData LIMIT 1")).scalar()
    assert stored == grader.CreatorID


def test_record_update_adds_result_columns_and_saves_decision(client, db_session):
    _seed_rows(db_session, count=1)
    row_key = _row_keys(client)[0]

    response = client.patch(
        f"/api/sdd/records/{row_key}",
        json={"decision": 2, "stage": 3, "comment": "Present"},
    )

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
    stored = db_session.execute(
        text("SELECT decision, stage, comment FROM SDDGradingData LIMIT 1")
    ).one()
    assert stored == (2, 3, "Present")


def test_record_update_matches_nullable_key_columns(client, db_session):
    db_session.execute(
        text(
            "INSERT INTO SDDGradingData "
            "(grader, pdb, sdb, bscan, x_start, x_end, width_px, laterality, oct_dcm_path, SubTaskID) "
            "VALUES (NULL, :pdb, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL)"
        ),
        {"pdb": "nullable-key"},
    )
    db_session.commit()
    row_key = client.get("/api/sdd/records").json()["rows"][0]["row_key"]

    response = client.patch(
        f"/api/sdd/records/{row_key}",
        json={"decision": 0, "stage": 1, "comment": "Present"},
    )

    assert response.status_code == 200
    stored = db_session.execute(
        text("SELECT decision, stage, comment FROM SDDGradingData WHERE pdb = :pdb"),
        {"pdb": "nullable-key"},
    ).one()
    assert stored == (0, 1, "Present")


def test_non_admin_is_forbidden(db_session, admin_user):
    _admin, grader = admin_user
    _seed_rows(db_session, count=1)

    app = FastAPI()
    app.include_router(sdd_router, prefix="/api")

    def override_db():
        yield db_session

    def override_user():
        return CurrentUser(creator_id=grader.CreatorID, username="grader-user")

    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[get_current_user] = override_user
    client = TestClient(app)

    assert client.get("/api/sdd/assignment").status_code == 403
    assert client.get("/api/sdd/assignment").json()["detail"] == "Admin access required"
