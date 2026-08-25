from backend.assistant_context import (
    RetentionMarkers,
    RetentionTransport,
    derive_retention_injected_marker,
    inspect_retention_artifacts,
    new_retention_markers,
)


def test_retention_markers_are_independent_and_at_least_128_bits() -> None:
    first = new_retention_markers()
    second = new_retention_markers()

    assert first.raw_request.startswith("anw-raw-")
    assert first.injected_message.startswith("anw-injected-")
    assert len(first.raw_request.removeprefix("anw-raw-")) == 32
    assert len(first.injected_message.removeprefix("anw-injected-")) == 32
    assert first.raw_request != first.injected_message
    assert first.injected_message == derive_retention_injected_marker(
        first.raw_request,
    )
    assert first != second


def test_no_marker_retention_allows_direct_json_candidate() -> None:
    markers = RetentionMarkers("raw-marker", "injected-marker")

    report = inspect_retention_artifacts(
        {"history": {"messages": ["ordinary text"]}, "log": "clean"},
        markers,
    )

    assert report.raw_request_locations == ()
    assert report.injected_message_locations == ()
    assert report.transport is RetentionTransport.DIRECT_JSON


def test_raw_request_retention_requires_context_ref_candidate() -> None:
    markers = RetentionMarkers("raw-marker", "injected-marker")

    report = inspect_retention_artifacts(
        {
            "chat-history": ["ordinary text"],
            "error-dump": {"request": {"request_context": "raw-marker"}},
        },
        markers,
    )

    assert report.raw_request_locations == ("error-dump",)
    assert report.injected_message_locations == ()
    assert report.transport is RetentionTransport.CONTEXT_REF


def test_injected_message_retention_requires_workbench_session() -> None:
    markers = RetentionMarkers("raw-marker", "injected-marker")

    report = inspect_retention_artifacts(
        {
            "error-dump": "raw-marker",
            "session-state": {
                "agent": {"state": {"context": ["injected-marker"]}},
            },
            "export": ["unrelated"],
        },
        markers,
    )

    assert report.raw_request_locations == ("error-dump",)
    assert report.injected_message_locations == ("session-state",)
    assert report.transport is RetentionTransport.WORKBENCH_SESSION


def test_marker_scan_handles_mapping_keys_and_nested_sequences() -> None:
    markers = RetentionMarkers("raw-marker", "injected-marker")

    report = inspect_retention_artifacts(
        {
            "trace": {"raw-marker": [1, ("injected-marker",)]},
        },
        markers,
    )

    assert report.raw_request_locations == ("trace",)
    assert report.injected_message_locations == ("trace",)
    assert report.transport is RetentionTransport.WORKBENCH_SESSION
