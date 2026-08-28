from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

from starlette.requests import Request

from backend.narration.production_runtime import ValidationRuntimeScope
from backend.narration.validation_access import validation_request_scope_authorized


NOVEL_ID = UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa")
DOCUMENT_ID = UUID("bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb")


def _scope(*, expired: bool = False) -> ValidationRuntimeScope:
    offset = timedelta(seconds=-1 if expired else 3_600)
    return ValidationRuntimeScope(
        novel_id=NOVEL_ID,
        document_id=DOCUMENT_ID,
        expires_at=datetime.now(timezone.utc) + offset,
    )


def _request(
    path_params: dict[str, str],
    *,
    headers: list[tuple[bytes, bytes]] | None = None,
    query_string: bytes = b"",
) -> Request:
    return Request(
        {
            "type": "http",
            "method": "GET",
            "scheme": "http",
            "server": ("127.0.0.1", 80),
            "client": ("127.0.0.1", 10000),
            "root_path": "",
            "path": "/api/test",
            "raw_path": b"/api/test",
            "query_string": query_string,
            "headers": headers or [],
            "path_params": path_params,
        }
    )


class _Rows:
    def __init__(self, value: object) -> None:
        self._value = value

    def one_or_none(self) -> object:
        return self._value


class _Session:
    def __init__(
        self,
        *,
        rows: list[object] | None = None,
        scalars: list[object] | None = None,
    ) -> None:
        self.rows = list(rows or [])
        self.scalars = list(scalars or [])

    def execute(self, _statement: object) -> _Rows:
        return _Rows(self.rows.pop(0))

    def scalar(self, _statement: object) -> object:
        return self.scalars.pop(0)


def test_direct_validation_paths_are_bound_to_exact_novel_or_document() -> None:
    session = _Session()
    scope = _scope()

    assert validation_request_scope_authorized(
        session,  # type: ignore[arg-type]
        _request({"document_id": str(DOCUMENT_ID)}),
        scope,
    )
    assert validation_request_scope_authorized(
        session,  # type: ignore[arg-type]
        _request({"novel_id": str(NOVEL_ID)}),
        scope,
    )
    assert not validation_request_scope_authorized(
        session,  # type: ignore[arg-type]
        _request({"document_id": str(uuid4())}),
        scope,
    )
    assert not validation_request_scope_authorized(
        session,  # type: ignore[arg-type]
        _request({"unknown_id": str(DOCUMENT_ID)}),
        scope,
    )


def test_indirect_resources_must_resolve_to_exact_chapter_scope() -> None:
    scope = _scope()
    matching = (NOVEL_ID, DOCUMENT_ID)
    wrong = (NOVEL_ID, uuid4())

    for key in ("request_id", "edition_id", "script_id", "version_id"):
        assert validation_request_scope_authorized(
            _Session(rows=[matching]),  # type: ignore[arg-type]
            _request({key: str(uuid4())}),
            scope,
        )
        assert not validation_request_scope_authorized(
            _Session(rows=[wrong]),  # type: ignore[arg-type]
            _request({key: str(uuid4())}),
            scope,
        )


def test_media_requires_one_scoped_authority_header_and_matching_asset() -> None:
    scope = _scope()
    asset_id = uuid4()
    edition_id = uuid4()
    preview_id = uuid4()

    assert validation_request_scope_authorized(
        _Session(  # type: ignore[arg-type]
            rows=[(NOVEL_ID, DOCUMENT_ID)],
            scalars=[NOVEL_ID],
        ),
        _request(
            {"asset_id": str(asset_id)},
            headers=[
                (b"x-narration-edition-id", str(edition_id).encode("ascii"))
            ],
        ),
        scope,
    )
    assert validation_request_scope_authorized(
        _Session(  # type: ignore[arg-type]
            rows=[(NOVEL_ID, asset_id)],
            scalars=[NOVEL_ID],
        ),
        _request(
            {"asset_id": str(asset_id)},
            headers=[
                (
                    b"x-narration-voice-preview-id",
                    str(preview_id).encode("ascii"),
                )
            ],
        ),
        scope,
    )
    assert not validation_request_scope_authorized(
        _Session(scalars=[NOVEL_ID]),  # type: ignore[arg-type]
        _request({"asset_id": str(asset_id)}),
        scope,
    )
    assert not validation_request_scope_authorized(
        _Session(scalars=[uuid4()]),  # type: ignore[arg-type]
        _request(
            {"asset_id": str(asset_id)},
            headers=[
                (b"x-narration-edition-id", str(edition_id).encode("ascii"))
            ],
        ),
        scope,
    )


def test_expired_or_noncanonical_scope_requests_fail_closed() -> None:
    assert not validation_request_scope_authorized(
        _Session(),  # type: ignore[arg-type]
        _request({"document_id": str(DOCUMENT_ID)}),
        _scope(expired=True),
    )
    assert not validation_request_scope_authorized(
        _Session(),  # type: ignore[arg-type]
        _request({"document_id": "BBBBBBBB-BBBB-4BBB-8BBB-BBBBBBBBBBBB"}),
        _scope(),
    )
    assert validation_request_scope_authorized(
        _Session(),  # type: ignore[arg-type]
        _request({}, query_string=f"novel_id={NOVEL_ID}".encode("ascii")),
        _scope(),
    )
