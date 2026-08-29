export const OUTLINE_CHARACTER_DRAFT_SCHEMA_VERSION = "outline-character-draft/2" as const;


export type OutlineCharacterRoleType = "main" | "supporting";


export type OutlineCharacterGender = "男" | "女" | "其他" | "未知";


export type OutlineCharacterDraftOrigin = "ai_candidate" | "manual";


/**
 * Lightweight outline-only character data. Formal profile and story-time state
 * stay outside this contract and are materialized by the backend explicitly.
 */
export interface OutlineCharacterDraftV2 {
  readonly schema_version: typeof OUTLINE_CHARACTER_DRAFT_SCHEMA_VERSION;
  readonly draft_key: string;
  readonly character_id: string | null;
  readonly role_type: OutlineCharacterRoleType;
  readonly name: string;
  readonly gender: OutlineCharacterGender;
  readonly age_at_story_start_note: string;
  readonly identity_summary: string;
  readonly personality_summary: string;
  readonly core_goal: string;
  readonly bio: string;
  readonly origin: OutlineCharacterDraftOrigin;
}


export interface ExistingCharacterSummary {
  readonly character_id: string;
  readonly name: string;
  readonly role_type: OutlineCharacterRoleType;
}


export interface OutlineCharacterNameConflict {
  readonly code: "character_link_required";
  readonly draft_key: string;
  readonly draft_name: string;
  readonly candidates: readonly ExistingCharacterSummary[];
}


export type CharacterNameConflictResolution =
  | {
      readonly kind: "link_existing";
      readonly character_id: string;
    }
  | {
      readonly kind: "create_new";
      readonly renamed_name: string;
    };


export interface NameConflictDecisionState {
  readonly mode: "unresolved" | "link_existing" | "create_new";
  readonly existing_character_id: string | null;
  readonly renamed_name: string;
}


export type OutlineCharacterDraftField = Exclude<
  keyof OutlineCharacterDraftV2,
  "schema_version"
>;


export interface OutlineCharacterDraftIssue {
  readonly draft_key: string;
  readonly field: OutlineCharacterDraftField | "characters";
  readonly code:
    | "required"
    | "invalid_value"
    | "too_long"
    | "duplicate_draft_key"
    | "duplicate_name";
  readonly message: string;
}


export type CharacterGenerationPhase = "idle" | "generating" | "ready" | "failed";


export interface CharacterGenerationState {
  readonly phase: CharacterGenerationPhase;
  readonly failure_message: string | null;
}


export type CharacterRegenerationScope =
  | "ai_generated_only"
  | "all_drafts"
  | "selected_drafts";


export interface CharacterRegenerationConfirmationState {
  readonly scope: CharacterRegenerationScope;
  readonly selected_draft_keys: readonly string[];
  readonly manual_replacement_acknowledged: boolean;
}


export interface CharacterRegenerationPlan {
  readonly scope: CharacterRegenerationScope;
  readonly replace_draft_keys: readonly string[];
  readonly preserve_draft_keys: readonly string[];
}


export class OutlineCharacterDraftContractError extends Error {
  constructor(
    readonly code:
      | "draft_not_found"
      | "candidate_not_found"
      | "rename_required"
      | "invalid_resolution"
      | "regeneration_confirmation_required",
    message: string,
  ) {
    super(message);
    this.name = "OutlineCharacterDraftContractError";
  }
}
