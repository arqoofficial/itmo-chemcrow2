from fastapi.testclient import TestClient
from unittest.mock import patch
from app.main import app

client = TestClient(app)


def test_queue_background_tool_returns_202():
    with patch("app.api.routes.internal.run_s2_search") as mock_task:
        mock_task.delay.return_value = None
        with patch("app.api.routes.internal.get_sync_redis") as mock_redis:
            mock_redis.return_value.set = lambda *a, **kw: None
            resp = client.post("/internal/queue-background-tool", json={
                "type": "s2_search",
                "conversation_id": "00000000-0000-0000-0000-000000000001",
                "query": "aspirin synthesis",
                "max_results": 5,
            })
    assert resp.status_code == 202


def test_queue_background_tool_saves_query_to_redis():
    saved = {}
    saved_kwargs = {}

    def mock_set(key, value, **kwargs):
        saved[key] = value
        saved_kwargs[key] = kwargs

    with patch("app.api.routes.internal.run_s2_search") as mock_task, \
         patch("app.api.routes.internal.get_sync_redis") as mock_redis:
        mock_task.delay.return_value = None
        mock_r = mock_redis.return_value
        mock_r.set.side_effect = mock_set

        resp = client.post("/internal/queue-background-tool", json={
            "type": "s2_search",
            "conversation_id": "00000000-0000-0000-0000-000000000001",
            "query": "aspirin synthesis",
            "max_results": 5,
        })

    assert resp.status_code == 202
    assert "s2_last_query:00000000-0000-0000-0000-000000000001" in saved
    assert saved["s2_last_query:00000000-0000-0000-0000-000000000001"] == "aspirin synthesis"
    assert saved_kwargs["s2_last_query:00000000-0000-0000-0000-000000000001"].get("ex") == 86400
