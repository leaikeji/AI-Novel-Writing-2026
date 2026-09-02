from backend.retrieval_summary import retrieval_summary


def test_hybrid_summary_is_redacted() -> None:
    summary = retrieval_summary(
        {
            "mode": "hybrid",
            "hits": [{"snippet": "private", "query": "secret"}],
            "provider_request_id": "provider-secret",
        }
    )
    assert summary == {
        "schema_version": "retrieval-summary/1",
        "outcome": "used",
        "mode": "hybrid",
        "reason_code": "ready",
        "hit_count": 1,
        "index_state": "ready",
    }
    assert "private" not in repr(summary)


def test_failed_retrieval_without_real_lexical_execution_is_context_only() -> None:
    summary = retrieval_summary(
        {"mode": "context_only", "hits": [], "degraded_reason": "network_timeout"}
    )
    assert summary["outcome"] == "degraded"
    assert summary["mode"] == "context_only"
    assert summary["reason_code"] == "provider_unavailable"


def test_missing_snapshot_is_explicitly_not_run() -> None:
    assert retrieval_summary(None)["outcome"] == "not_run"
