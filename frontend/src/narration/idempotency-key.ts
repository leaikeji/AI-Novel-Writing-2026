/**
 * Idempotency identifiers are collision guards, not credentials. Prefer the
 * browser UUID API, but keep local author actions usable in restricted PawApp
 * webviews where that API is absent or throws.
 */
export function createNarrationActionUuid(): string {
  try {
    const cryptography = typeof window === "undefined" ? undefined : window.crypto;
    if (typeof cryptography?.randomUUID === "function") {
      return cryptography.randomUUID();
    }
  } catch {
    // Continue with an RFC 4122-shaped local fallback.
  }

  const bytes = Array.from({ length: 16 }, () => Math.floor(Math.random() * 256));
  bytes[6] = ((bytes[6] ?? 0) & 0x0f) | 0x40;
  bytes[8] = ((bytes[8] ?? 0) & 0x3f) | 0x80;
  const hex = bytes.map((value) => value.toString(16).padStart(2, "0")).join("");
  return `${hex.slice(0, 8)}-${hex.slice(8, 12)}-${hex.slice(12, 16)}-${
    hex.slice(16, 20)
  }-${hex.slice(20)}`;
}


export function createNarrationIdempotencyKey(
  prefix: string,
  separator: "-" | ":" = "-",
): string {
  const normalized = prefix.trim();
  if (normalized === "") throw new Error("idempotency key prefix is required");
  return `${normalized}${separator}${createNarrationActionUuid()}`;
}
