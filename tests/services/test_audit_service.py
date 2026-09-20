from src.services import audit_service


async def test_records_never_raise_when_session_is_unavailable(monkeypatch):
    def boom_session():
        raise RuntimeError("database not initialized")

    monkeypatch.setattr(audit_service.db, "session", boom_session)
    await audit_service.record_chat_turn(question="q", mode="answer")
    await audit_service.record_error(component="qa", message="boom")
    await audit_service.record_llm_usage({"model": "mock-model", "task": "themes"})


async def test_records_never_raise_when_repository_fails(monkeypatch):
    class BoomSession:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

    async def boom_add_chat_turn(**kwargs):
        raise RuntimeError("write failed")

    monkeypatch.setattr(audit_service, "AuditRepository", lambda session: type(
        "R", (), {"add_chat_turn": boom_add_chat_turn}
    )())
    monkeypatch.setattr(audit_service.db, "session", lambda: BoomSession())
    await audit_service.record_chat_turn(question="q", mode="answer")