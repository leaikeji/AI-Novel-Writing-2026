/** Validated, content-free metadata from a frozen packet, not the current catalog. */
export interface MethodItem {
  readonly skill_id: string;
  readonly display_name: string;
  readonly version: string | null;
  readonly body_sha256: string;
  readonly reference_count: number;
  readonly basis: "primary" | "explicit" | "deterministic" | "semantic";
  readonly evidence_refs: readonly string[];
}
export interface MethodDetails {
  readonly schema_version: "writing-method-details/1";
  readonly primary_skill: string;
  readonly methods: readonly MethodItem[];
  readonly reasons: readonly string[];
  readonly estimated_tokens: number;
}
const ID = /^[a-z][a-z0-9-]{0,63}$/;
const HASH = /^[a-f0-9]{64}$/;
function object(value: unknown): Record<string, unknown> | null {
  return value !== null && typeof value === "object" && !Array.isArray(value) ? value as Record<string, unknown> : null;
}
function codes(value: unknown): readonly string[] | null {
  return Array.isArray(value) && value.length <= 256 && value.every(v => typeof v === "string" && /^[a-zA-Z0-9_.:/,-]{1,240}$/.test(v))
    ? Object.freeze([...value]) : null;
}
export function parseMethodDetails(value: unknown): MethodDetails | null {
  const data = object(value);
  if (!data || data.schema_version !== "writing-method-details/1" || typeof data.primary_skill !== "string"
    || !ID.test(data.primary_skill) || !Array.isArray(data.methods) || data.methods.length > 16
    || !Number.isSafeInteger(data.estimated_tokens) || Number(data.estimated_tokens) < 0) return null;
  const reasons = codes(data.reasons);
  if (!reasons) return null;
  const methods: MethodItem[] = [];
  for (const raw of data.methods) {
    const item = object(raw);
    if (!item || typeof item.skill_id !== "string" || !ID.test(item.skill_id)
      || typeof item.display_name !== "string" || !item.display_name || item.display_name.length > 80
      || (item.version !== null && (typeof item.version !== "string" || !/^\d+\.\d+\.\d+$/.test(item.version)))
      || typeof item.body_sha256 !== "string" || !HASH.test(item.body_sha256)
      || !Number.isSafeInteger(item.reference_count) || Number(item.reference_count) < 0
      || !["primary", "explicit", "deterministic", "semantic"].includes(String(item.basis))) return null;
    const refs = codes(item.evidence_refs);
    if (!refs || methods.some(m => m.skill_id === item.skill_id)) return null;
    methods.push(Object.freeze({ skill_id: item.skill_id, display_name: item.display_name, version: item.version as string | null,
      body_sha256: item.body_sha256, reference_count: Number(item.reference_count),
      basis: item.basis as MethodItem["basis"], evidence_refs: refs }));
  }
  if (!methods.some(m => m.skill_id === data.primary_skill && m.basis === "primary")) return null;
  return Object.freeze({ schema_version: "writing-method-details/1", primary_skill: data.primary_skill,
    methods: Object.freeze(methods), reasons, estimated_tokens: Number(data.estimated_tokens) });
}
