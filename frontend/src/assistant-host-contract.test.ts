import { describe, expectTypeOf, it } from "vitest";


describe("QwenPaw public host contract", () => {
  it("keeps agent and session identity narrow", () => {
    expectTypeOf<Window["QwenPaw"]["host"]["getSelectedAgentId"]>()
      .returns.toEqualTypeOf<string | null>();
    expectTypeOf<Window["QwenPaw"]["host"]["getCurrentSessionId"]>()
      .returns.toEqualTypeOf<string | null>();
  });

  it("models the verified disposable chat extension points", () => {
    expectTypeOf<ReturnType<
      Window["QwenPaw"]["chat"]["sender"]["addSuggestion"]
    >>().toEqualTypeOf<QwenPawDisposable>();
    expectTypeOf<ReturnType<
      Window["QwenPaw"]["chat"]["requestPayload"]["add"]
    >>().toEqualTypeOf<QwenPawDisposable>();
    expectTypeOf<ReturnType<
      Window["QwenPaw"]["chat"]["toolRender"]
    >>().toEqualTypeOf<QwenPawDisposable>();
  });
});
