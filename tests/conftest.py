"""Shared fixtures — Sprint 1 tests run against the real PostgreSQL DB.

Each test gets a fresh TestClient (fresh cookie jar, so logins never
leak between tests) and, where needed, a fresh throwaway user created
in the DB and deleted afterwards — so agent instruct tests never share
a rate-limit bucket with each other or with manual live testing.
"""
import uuid
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

from app.core.security import PWD
from app.db import models
from app.db.session import SessionLocal
from app.main import app


@pytest.fixture()
def client():
    return TestClient(app)


@pytest.fixture()
def db():
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture()
def make_user(db):
    """Create a throwaway user; delete it and its runs afterwards."""
    created = []

    def _make(role: str) -> models.User:
        user = models.User(
            email=f"test-{uuid.uuid4().hex[:8]}@almadar.local",
            name="Test User",
            role=role,
            password_hash=PWD.hash("Test123!"),
            created_at=datetime.now(timezone.utc).replace(tzinfo=None),
        )
        db.add(user)
        db.commit()
        created.append(user.id)
        return user

    yield _make

    for user_id in created:
        # Audit rows reference the user (FK) — remove them first.
        db.query(models.AuditLog).filter(
            models.AuditLog.user_id == user_id
        ).delete(synchronize_session=False)
        # Agent memory rows reference the user AND the run (FK) — they
        # must go before the runs are deleted, or the user delete is
        # blocked by agent_memory.user_id.
        db.query(models.AgentMemory).filter(
            models.AgentMemory.user_id == user_id
        ).delete(synchronize_session=False)
        # Approvals the user requested or approved (not only approvals
        # on their own runs) also reference the user.
        db.query(models.Approval).filter(
            models.Approval.requested_by == user_id
        ).delete(synchronize_session=False)
        db.query(models.Approval).filter(
            models.Approval.approver_id == user_id
        ).delete(synchronize_session=False)
        runs = db.query(models.WorkflowRun).filter(
            models.WorkflowRun.user_id == user_id
        ).all()
        run_ids = [r.id for r in runs]
        if run_ids:
            steps = db.query(models.WorkflowStep).filter(
                models.WorkflowStep.run_id.in_(run_ids)
            ).all()
            step_ids = [s.id for s in steps]
            if step_ids:
                db.query(models.ToolCall).filter(
                    models.ToolCall.step_id.in_(step_ids)
                ).delete(synchronize_session=False)
            db.query(models.WorkflowStep).filter(
                models.WorkflowStep.run_id.in_(run_ids)
            ).delete(synchronize_session=False)
            db.query(models.Approval).filter(
                models.Approval.run_id.in_(run_ids)
            ).delete(synchronize_session=False)
            db.query(models.EmailDraft).filter(
                models.EmailDraft.run_id.in_(run_ids)
            ).delete(synchronize_session=False)
            exports = db.query(models.ReportExport).filter(
                models.ReportExport.run_id.in_(run_ids)
            ).all()
            for export in exports:
                try:
                    import os

                    os.remove(export.file_path)
                except OSError:
                    pass
            db.query(models.ReportExport).filter(
                models.ReportExport.run_id.in_(run_ids)
            ).delete(synchronize_session=False)
            db.query(models.WorkflowRun).filter(
                models.WorkflowRun.user_id == user_id
            ).delete(synchronize_session=False)
        db.query(models.User).filter(models.User.id == user_id).delete(
            synchronize_session=False
        )
    db.commit()


def login_as(client, email: str, password: str):
    """Log in and return the response; the client keeps the cookies."""
    return client.post(
        "/api/v1/auth/login", json={"email": email, "password": password}
    )
