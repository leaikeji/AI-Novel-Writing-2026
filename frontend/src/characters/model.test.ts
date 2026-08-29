import { describe, expect, it } from "vitest";

import {
  buildSaveCommand,
  characterWorkspaceTabFromKey,
  isMultiTimeline,
  profileDraftFromWorkspace,
  rootDraftFromWorkspace,
  tabForField,
  updateProfileText,
} from "./model";
import { characterWorkspace, multiTimelineWorkspace } from "./test-fixtures";

describe("character workspace model", () => {
  it("supports wrapping keyboard navigation without consuming unrelated keys", () => {
    expect(characterWorkspaceTabFromKey("basic", "ArrowLeft")).toBe("voice");
    expect(characterWorkspaceTabFromKey("voice", "ArrowRight")).toBe("basic");
    expect(characterWorkspaceTabFromKey("growth", "Home")).toBe("basic");
    expect(characterWorkspaceTabFromKey("basic", "End")).toBe("voice");
    expect(characterWorkspaceTabFromKey("basic", "Enter")).toBeNull();
  });

  it("only exposes multi-line mode when more than one timeline exists", () => {
    expect(isMultiTimeline(characterWorkspace())).toBe(false);
    expect(isMultiTimeline(multiTimelineWorkspace())).toBe(true);
  });

  it("builds a CAS command and preserves unknown profile extensions", () => {
    const workspace = characterWorkspace();
    const root = { ...rootDraftFromWorkspace(workspace), name: "林舟（改名后）" };
    const profile = updateProfileText(
      profileDraftFromWorkspace(workspace),
      "goals",
      "寻找姐姐\n保护书店",
      true,
    );
    const command = buildSaveCommand(workspace, root, profile);

    expect(command.expected_character_version).toBe(4);
    expect(command.expected_instance_version).toBe(7);
    expect(command.expected_character_catalog_version).toBe(11);
    expect(command.expected_story_ledger_version).toBe(19);
    expect(command.root?.name).toBe("林舟（改名后）");
    expect(command.profile?.goals).toEqual(["寻找姐姐", "保护书店"]);
    expect(command.profile?.custom_extension).toBe("必须保留");
  });

  it("routes server field errors to the correct tab", () => {
    expect(tabForField("character.name")).toBe("basic");
    expect(tabForField("profile.true_identity")).toBe("line-profile");
  });
});
