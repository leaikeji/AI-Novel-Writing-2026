from uuid import uuid4

import pytest
from pydantic import ValidationError

from backend.writing_skills.contracts import (
    ActionIdentity, FrozenRouteRequest, MethodPreferences, ReferenceRule,
    Scope, SourceItem, TaskModelInputProjectionV1,
)


def test_action_identity_is_independent_of_route_configuration():
    owner, workspace = uuid4(), uuid4()
    identity = ActionIdentity(owner_id=owner, workspace_id=workspace, entry="button", action_id=uuid4())
    projection = TaskModelInputProjectionV1(
        scope=Scope(owner_id=owner, workspace_id=workspace, kind="novel", scope_id=uuid4(), tab_id="tab"),
        task="chapter_body", intent="write", source_version="1", visibility_key="chapter-1",
        sources=(SourceItem(key="genre", kind="genre", text="悬疑"),),
    )
    request = FrozenRouteRequest(identity=identity, projection=projection, preferences=MethodPreferences(),
                                 catalog_version="a" * 64, provider_id="p", model_id="m")
    changed = request.model_copy(update={"catalog_version": "b" * 64, "model_id": "new"})
    assert request.identity.key == changed.identity.key
    assert request.route_request_key != changed.route_request_key
    with pytest.raises(ValidationError):
        request.model_id = "different"
    retry = request.model_copy(update={"identity": identity.model_copy(update={"action_id": uuid4()}),
                                       "retry_of_action_id": identity.action_id})
    assert retry.route_request_key == request.route_request_key
    with pytest.raises(ValidationError):
        request.model_copy(update={"retry_of_action_id": identity.action_id}).model_validate(
            request.model_copy(update={"retry_of_action_id": identity.action_id}).model_dump())


@pytest.mark.parametrize("path", ["references/../outside.md", "references//a.md", "/tmp/a.md"])
def test_reference_rejects_nonlocal_paths(path):
    with pytest.raises(ValidationError):
        ReferenceRule(key="r", path=path, tasks=("chapter_body",))


def test_conflicting_preferences_are_rejected():
    with pytest.raises(ValidationError):
        MethodPreferences(required_ids=("one",), excluded_ids=("one",))
    with pytest.raises(ValidationError):
        MethodPreferences(mode="generic_only", required_ids=("one",))


def test_client_cannot_add_authorization_flag():
    with pytest.raises(ValidationError):
        ActionIdentity(owner_id=uuid4(), workspace_id=uuid4(), entry="native", action_id=uuid4(), trusted=True)
