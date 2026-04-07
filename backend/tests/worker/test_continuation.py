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


@patch("app.worker.tasks.continuation.get_sync_redis")
@patch("app.worker.tasks.continuation.Session")
@patch("app.worker.tasks.continuation._process_streaming")
def test_run_agent_continuation_acquires_lock_streams_saves(
    mock_streaming, mock_session, mock_redis
):
    """Continuation acquires lock, loads history, streams, saves assistant message."""
    mock_r = MagicMock()
    mock_redis.return_value = mock_r
    mock_r.set.return_value = True  # lock acquired
    mock_r.llen.return_value = 0  # no pending

    mock_db = MagicMock()
    mock_session.return_value.__enter__ = lambda s: mock_db
    mock_session.return_value.__exit__ = MagicMock(return_value=False)

    msg1 = MagicMock()
    msg1.role = "user"
    msg1.content = "What is aspirin?"
    msg2 = MagicMock()
    msg2.role = "background"
    msg2.content = "[Background: Literature Search Results]\n..."
    mock_db.exec.return_value.all.return_value = [msg1, msg2]
    mock_db.get.return_value = MagicMock()  # Conversation

    mock_streaming.return_value = ("Aspirin is an analgesic.", None)

    def _refresh(obj):
        obj.id = "msg-uuid"
        obj.created_at = "2026-04-02T12:00:00"

    mock_db.refresh.side_effect = _refresh

    from app.worker.tasks.continuation import run_agent_continuation
    run_agent_continuation("conv-123")

    # Lock acquired and released
    mock_r.set.assert_called_with("conv_processing:conv-123", "1", nx=True, ex=600)
    mock_r.delete.assert_any_call("conv_processing:conv-123")

    # Streaming called with correct message payload
    mock_streaming.assert_called_once()
    call_args = mock_streaming.call_args[0]
    assert call_args[0] == "conv-123"

    # Assistant message saved
    mock_db.add.assert_called()
    saved = next(
        call[0][0] for call in mock_db.add.call_args_list
        if hasattr(call[0][0], 'role') and call[0][0].role == "assistant"
    )
    assert saved.content == "Aspirin is an analgesic."


@patch("app.worker.tasks.continuation.get_sync_redis")
def test_run_agent_continuation_queues_if_locked(mock_redis):
    """If lock is taken, push to conv_pending and return without streaming."""
    mock_r = MagicMock()
    mock_redis.return_value = mock_r
    mock_r.set.return_value = None  # lock NOT acquired

    with patch("app.worker.tasks.continuation._process_streaming") as mock_streaming:
        from app.worker.tasks.continuation import run_agent_continuation
        run_agent_continuation("conv-123")

    mock_r.rpush.assert_called_once_with("conv_pending:conv-123", "1")
    mock_streaming.assert_not_called()


@patch("app.worker.tasks.continuation.get_sync_redis")
@patch("app.worker.tasks.continuation.Session")
@patch("app.worker.tasks.continuation._process_streaming")
def test_run_agent_continuation_drains_pending_queue(
    mock_streaming, mock_session, mock_redis
):
    """After finishing, drain conv_pending and dispatch one new continuation."""
    import app.worker.tasks.continuation as cont_mod

    mock_r = MagicMock()
    mock_redis.return_value = mock_r
    mock_r.set.return_value = True  # lock acquired
    mock_r.llen.return_value = 3   # 3 pending signals

    mock_db = MagicMock()
    mock_session.return_value.__enter__ = lambda s: mock_db
    mock_session.return_value.__exit__ = MagicMock(return_value=False)
    mock_db.exec.return_value.all.return_value = []
    mock_db.get.return_value = MagicMock()
    mock_db.refresh.side_effect = lambda obj: setattr(obj, "id", "x")
    mock_streaming.return_value = ("", None)

    # Patch only apply_async to prevent real dispatch while still running the real function
    mock_apply_async = MagicMock()
    real_fn = cont_mod.run_agent_continuation
    with patch.object(real_fn, "apply_async", mock_apply_async):
        cont_mod.run_agent_continuation("conv-123")

    # Full queue deleted, single continuation dispatched
    mock_r.delete.assert_any_call("conv_pending:conv-123")
    mock_apply_async.assert_called_once_with(args=["conv-123"], countdown=0)


# ── _format_s2_results ────────────────────────────────────────────────────────

def test_format_s2_results_happy_path():
    """Single paper with all fields → correct heading and content."""
    from app.worker.tasks.continuation import _format_s2_results
    papers = [{
        "title": "Aspirin Synthesis Review",
        "authors": "Alice, Bob",
        "year": 2023,
        "doi": "10.1234/asp",
        "abstract": "A review of aspirin synthesis.",
    }]
    result = _format_s2_results(papers, "aspirin")
    assert "[Background: Literature Search Results]" in result
    assert 'search for "aspirin" found 1 paper' in result
    assert "Aspirin Synthesis Review" in result
    assert "10.1234/asp" in result
    assert "2023" in result
    assert "Alice, Bob" in result
    assert "A review of aspirin synthesis." in result


def test_format_s2_results_truncates_abstract_at_400_chars():
    """Abstract longer than 400 chars gets truncated with '...'."""
    from app.worker.tasks.continuation import _format_s2_results
    long_abstract = "x" * 500
    papers = [{"title": "T", "authors": "A", "year": 2024, "doi": "10.1/x", "abstract": long_abstract}]
    result = _format_s2_results(papers, "query")
    assert "x" * 400 + "..." in result
    assert "x" * 401 not in result


def test_format_s2_results_missing_optional_fields():
    """Paper with no doi, abstract, year → uses fallback strings, no crash."""
    from app.worker.tasks.continuation import _format_s2_results
    papers = [{"title": "Minimal Paper"}]
    result = _format_s2_results(papers, "query")
    assert "Minimal Paper" in result
    assert "DOI: N/A" in result      # doi fallback
    assert "(N/A)" in result          # year fallback
    assert "No abstract." in result  # abstract fallback


def test_format_s2_results_multiple_papers():
    """Multiple papers are numbered sequentially."""
    from app.worker.tasks.continuation import _format_s2_results
    papers = [
        {"title": "Paper One", "doi": "10.1/1"},
        {"title": "Paper Two", "doi": "10.1/2"},
        {"title": "Paper Three", "doi": "10.1/3"},
    ]
    result = _format_s2_results(papers, "q")
    assert "1. **Paper One**" in result
    assert "2. **Paper Two**" in result
    assert "3. **Paper Three**" in result


# ── _trigger_rag_continuation ─────────────────────────────────────────────────

@patch("app.worker.tasks.continuation.run_agent_continuation")
@patch("app.worker.tasks.continuation.save_background_message")
@patch("app.worker.tasks.continuation._publish_sync")
@patch("app.worker.tasks.continuation.get_sync_redis")
def test_trigger_rag_continuation_with_redis_metadata(
    mock_redis, mock_publish, mock_save, mock_continuation
):
    """Job IDs with Redis metadata → paper titles in PAPERS_INGESTED message."""
    mock_r = MagicMock()
    mock_redis.return_value = mock_r
    mock_r.get.return_value = json.dumps({
        "title": "Aspirin Review", "authors": "Alice", "year": 2023, "doi": "10.1/asp"
    })

    from app.worker.tasks.continuation import _trigger_rag_continuation
    _trigger_rag_continuation("conv-abc", ["job-1"])

    # Background message saved with PAPERS_INGESTED content
    mock_save.assert_called_once()
    conv_id, content = mock_save.call_args[0]
    assert conv_id == "conv-abc"
    assert "[Background: New Papers Available]" in content
    assert "Aspirin Review" in content
    assert mock_save.call_args.kwargs.get("variant") == "info"

    # background_update SSE published
    mock_publish.assert_called_once_with("conv-abc", {"event": "background_update"})

    # Continuation dispatched with countdown=1
    mock_continuation.apply_async.assert_called_once_with(args=["conv-abc"], countdown=1)


@patch("app.worker.tasks.continuation.run_agent_continuation")
@patch("app.worker.tasks.continuation.save_background_message")
@patch("app.worker.tasks.continuation._publish_sync")
@patch("app.worker.tasks.continuation.get_sync_redis")
def test_trigger_rag_continuation_missing_redis_metadata(
    mock_redis, mock_publish, mock_save, mock_continuation
):
    """When Redis has no metadata for a job_id → uses fallback 'recently parsed articles'."""
    mock_r = MagicMock()
    mock_redis.return_value = mock_r
    mock_r.get.return_value = None  # metadata expired or missing

    from app.worker.tasks.continuation import _trigger_rag_continuation
    _trigger_rag_continuation("conv-abc", ["job-orphan"])

    conv_id, content = mock_save.call_args[0]
    assert "recently parsed articles" in content
    mock_publish.assert_called_once_with("conv-abc", {"event": "background_update"})
    mock_continuation.apply_async.assert_called_once_with(args=["conv-abc"], countdown=1)


@patch("app.worker.tasks.continuation.run_agent_continuation")
@patch("app.worker.tasks.continuation.save_background_message")
@patch("app.worker.tasks.continuation._publish_sync")
@patch("app.worker.tasks.continuation.get_sync_redis")
def test_trigger_rag_continuation_no_job_ids(
    mock_redis, mock_publish, mock_save, mock_continuation
):
    """Called with completed_job_ids=None (manual trigger) → generic fallback message."""
    mock_r = MagicMock()
    mock_redis.return_value = mock_r

    from app.worker.tasks.continuation import _trigger_rag_continuation
    _trigger_rag_continuation("conv-abc", None)

    conv_id, content = mock_save.call_args[0]
    assert "[Background: New Papers Available]" in content
    assert "recently parsed articles" in content
    mock_continuation.apply_async.assert_called_once_with(args=["conv-abc"], countdown=1)
