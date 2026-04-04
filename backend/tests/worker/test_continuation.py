from unittest.mock import MagicMock, patch
import json
import pytest


@patch("app.worker.tasks.continuation.run_agent_continuation")
@patch("app.worker.tasks.continuation.get_sync_redis")
@patch("app.worker.tasks.continuation.httpx")
def test_monitor_ingestion_success_all_done(mock_httpx, mock_redis, mock_continuation):
    """All jobs fetched+parsed → save background message, dispatch continuation."""
    mock_client = MagicMock()
    mock_httpx.Client.return_value.__enter__ = lambda s: mock_client
    mock_httpx.Client.return_value.__exit__ = MagicMock(return_value=False)

    fetch_resp = MagicMock()
    fetch_resp.status_code = 200
    fetch_resp.json.return_value = {"status": "done"}

    parse_resp = MagicMock()
    parse_resp.status_code = 200
    parse_resp.json.return_value = {"status": "completed"}

    def _mock_get(url, **kwargs):
        # article-fetcher uses port 8200; pdf-parser uses port 8300
        if "8200" in url or "article-fetcher" in url:
            return fetch_resp
        return parse_resp

    mock_client.get.side_effect = _mock_get

    mock_r = MagicMock()
    mock_redis.return_value = mock_r
    mock_r.get.return_value = json.dumps({
        "title": "Paper A", "authors": "Alice", "year": 2023, "doi": "10.1/a"
    })

    with patch("app.worker.tasks.continuation.save_background_message") as mock_save, \
         patch("app.worker.tasks.continuation._publish_sync"):
        from app.worker.tasks.continuation import monitor_ingestion
        monitor_ingestion("conv-123", ["job-1"])

    mock_save.assert_called_once()
    args = mock_save.call_args[0]
    assert args[0] == "conv-123"
    assert "[Background: New Papers Available]" in args[1]
    mock_continuation.apply_async.assert_called_once()


@patch("app.worker.tasks.continuation.httpx")
@patch("app.worker.tasks.continuation.get_sync_redis")
def test_monitor_ingestion_404_is_pending_not_failed(mock_redis, mock_httpx):
    """pdf-parser 404 means 'not yet created' — treat as pending, not failed."""
    mock_client = MagicMock()
    mock_httpx.Client.return_value.__enter__ = lambda s: mock_client
    mock_httpx.Client.return_value.__exit__ = MagicMock(return_value=False)

    def _mock_get(url, **kwargs):
        resp = MagicMock()
        # article-fetcher uses port 8200; pdf-parser uses port 8300
        if "8200" in url or "article-fetcher" in url:
            resp.status_code = 200
            resp.json.return_value = {"status": "done"}
        else:
            resp.status_code = 404  # pdf-parser not yet created
        return resp

    mock_client.get.side_effect = _mock_get
    mock_redis.return_value = MagicMock()

    from celery.exceptions import Retry
    from app.worker.tasks.continuation import monitor_ingestion

    with patch.object(monitor_ingestion, "retry", side_effect=Retry) as mock_retry:
        with pytest.raises(Retry):
            monitor_ingestion("conv-123", ["job-1"])
    mock_retry.assert_called_once()


@patch("app.worker.tasks.continuation.run_agent_continuation")
@patch("app.worker.tasks.continuation.httpx")
@patch("app.worker.tasks.continuation.get_sync_redis")
def test_monitor_ingestion_all_fetch_failed_publishes_error(mock_redis, mock_httpx, mock_continuation):
    """All article-fetcher jobs failed → publish background_error, stop pipeline."""
    mock_client = MagicMock()
    mock_httpx.Client.return_value.__enter__ = lambda s: mock_client
    mock_httpx.Client.return_value.__exit__ = MagicMock(return_value=False)

    fetch_resp = MagicMock()
    fetch_resp.status_code = 200
    fetch_resp.json.return_value = {"status": "failed"}
    mock_client.get.return_value = fetch_resp
    mock_redis.return_value = MagicMock()

    with patch("app.worker.tasks.continuation._publish_sync") as mock_pub:
        from app.worker.tasks.continuation import monitor_ingestion
        monitor_ingestion("conv-123", ["job-1"])

    published = mock_pub.call_args[0][1]
    assert published["event"] == "background_error"
    mock_continuation.apply_async.assert_not_called()


def _make_papers():
    return [
        {
            "title": "Aspirin Synthesis Review",
            "authors": "Alice, Bob",
            "year": 2023,
            "doi": "10.1234/asp",
            "abstract": "A review of aspirin synthesis routes.",
            "citation_count": 42,
            "url": "https://example.com/paper1",
        }
    ]


@patch("app.worker.tasks.continuation.run_agent_continuation")
@patch("app.worker.tasks.continuation.monitor_ingestion")
@patch("app.worker.tasks.continuation._submit_article_jobs")
@patch("app.worker.tasks.continuation.httpx")
@patch("app.worker.tasks.continuation.get_sync_redis")
@patch("app.worker.tasks.continuation.Session")
def test_run_s2_search_success_path(
    mock_session, mock_redis, mock_httpx, mock_submit, mock_monitor, mock_continuation
):
    """Success: saves background message, dispatches continuation and monitor_ingestion."""
    mock_client = MagicMock()
    mock_httpx.Client.return_value.__enter__ = lambda s: mock_client
    mock_httpx.Client.return_value.__exit__ = MagicMock(return_value=False)
    mock_client.post.return_value.json.return_value = {"papers": _make_papers(), "query": "aspirin"}
    mock_client.post.return_value.raise_for_status = MagicMock()

    mock_r = MagicMock()
    mock_redis.return_value = mock_r
    mock_submit.return_value = [{"doi": "10.1234/asp", "job_id": "job-uuid-1"}]

    mock_db = MagicMock()
    mock_session.return_value.__enter__ = lambda s: mock_db
    mock_session.return_value.__exit__ = MagicMock(return_value=False)

    from app.worker.tasks.continuation import run_s2_search
    run_s2_search("conv-123", "aspirin", 5)

    # Background message saved
    mock_db.add.assert_called_once()
    saved_msg = mock_db.add.call_args[0][0]
    assert saved_msg.role == "background"
    assert "[Background: Literature Search Results]" in saved_msg.content
    assert saved_msg.msg_metadata == {"variant": "info"}

    # background_update SSE published with correct event
    assert mock_r.publish.call_count >= 1
    published_calls = [json.loads(call[0][1]) for call in mock_r.publish.call_args_list]
    assert any(p["event"] == "background_update" for p in published_calls)

    # Continuation dispatched with countdown=1
    mock_continuation.apply_async.assert_called_once_with(
        args=["conv-123"], countdown=1
    )

    # Paper metadata stored in Redis
    set_calls = mock_r.set.call_args_list
    assert any("s2_paper_meta:" in str(call) for call in set_calls)

    # Monitor dispatched
    mock_monitor.delay.assert_called_once()


@patch("app.worker.tasks.continuation.run_agent_continuation")
@patch("app.worker.tasks.continuation.httpx")
@patch("app.worker.tasks.continuation.get_sync_redis")
@patch("app.worker.tasks.continuation.Session")
def test_run_s2_search_no_papers_publishes_error_event(
    mock_session, mock_redis, mock_httpx, mock_continuation
):
    """No papers: publish background_error SSE, do NOT dispatch continuation."""
    mock_client = MagicMock()
    mock_httpx.Client.return_value.__enter__ = lambda s: mock_client
    mock_httpx.Client.return_value.__exit__ = MagicMock(return_value=False)
    mock_client.post.return_value.json.return_value = {"papers": [], "query": "xyz"}
    mock_client.post.return_value.raise_for_status = MagicMock()

    mock_r = MagicMock()
    mock_redis.return_value = mock_r

    from app.worker.tasks.continuation import run_s2_search
    run_s2_search("conv-123", "xyz", 5)

    # background_error SSE published
    published = json.loads(mock_r.publish.call_args[0][1])
    assert published["event"] == "background_error"

    # No continuation dispatched
    mock_continuation.apply_async.assert_not_called()


@patch("app.worker.tasks.continuation.run_agent_continuation")
@patch("app.worker.tasks.continuation.httpx")
@patch("app.worker.tasks.continuation.get_sync_redis")
def test_run_s2_search_s2_call_fails_publishes_error(
    mock_redis, mock_httpx, mock_continuation
):
    """S2 HTTP call raises exception → publish background_error with retry_available=True, no continuation."""
    mock_client = MagicMock()
    mock_httpx.Client.return_value.__enter__ = lambda s: mock_client
    mock_httpx.Client.return_value.__exit__ = MagicMock(return_value=False)
    mock_client.post.side_effect = Exception("Connection refused")

    mock_r = MagicMock()
    mock_redis.return_value = mock_r

    from app.worker.tasks.continuation import run_s2_search
    run_s2_search("conv-123", "aspirin", 5)

    published = json.loads(mock_r.publish.call_args[0][1])
    assert published["event"] == "background_error"
    assert published["retry_available"] is True
    mock_continuation.apply_async.assert_not_called()
