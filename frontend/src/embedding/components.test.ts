import { describe, expect, it, vi } from "vitest";

import {
  createEmbeddingConfigPage,
  type EmbeddingConfigPageApi,
} from "./embedding-config-page";
import {
  createNovelSemanticIndexCard,
  type NovelSemanticIndexCardApi,
} from "./novel-semantic-index-card";
import { config, consent, generation, novelStatus, TEST_NOVEL_ID } from "./test-fixtures";
import {
  TEST_ANTD,
  createReactHarness,
  findAll,
  findButton,
  settle,
  textContent,
} from "./test-harness";


describe("embedding configuration page", () => {
  it("keeps the key write-only and disables an unready candidate", async () => {
    const resource = config({
      candidate_generation: generation({
        state: "building",
        pending_novel_count: 1,
        ready_novel_count: 0,
        evaluation_state: "pending",
        activation_eligible: false,
      }),
    });
    const saveCandidate = vi.fn<EmbeddingConfigPageApi["saveCandidate"]>(
      () => new Promise(() => undefined),
    );
    const api: EmbeddingConfigPageApi = {
      getConfig: vi.fn().mockResolvedValue(resource),
      testConnection: vi.fn(),
      saveCandidate,
      rebuildCandidate: vi.fn(),
      cancelCandidate: vi.fn(),
      evaluateCandidate: vi.fn(),
      activateCandidate: vi.fn(),
      rollback: vi.fn(),
    };
    const harness = createReactHarness();
    const Component = createEmbeddingConfigPage(harness.React, TEST_ANTD, api);
    let root = harness.render(Component, {});
    harness.commitEffects();
    await settle();
    root = harness.render(Component, {});

    const secretInput = findAll(root, (element) => element.props.type === "password")[0];
    expect(secretInput.props.value).toBe("");
    expect(textContent(root)).toContain("write-only");
    expect(findButton(root, "激活候选").props.disabled).toBe(true);

    (secretInput.props.onChange as (event: unknown) => void)({
      target: { value: "secret-only-in-request" },
    });
    root = harness.render(Component, {});
    const save = findButton(root, "保存候选配置并替换 Key");
    (save.props.onClick as () => void)();
    root = harness.render(Component, {});

    expect(saveCandidate).toHaveBeenCalledWith(
      expect.objectContaining({
        api_key_action: "replace",
        api_key: "secret-only-in-request",
      }),
      expect.any(AbortSignal),
    );
    expect(findAll(root, (element) => element.props.type === "password")[0].props.value).toBe("");
    expect(textContent(root)).not.toContain("secret-only-in-request");
  });
});


describe("novel semantic index card", () => {
  it("discloses all cloud scopes before consent", async () => {
    const api: NovelSemanticIndexCardApi = {
      getConsent: vi.fn().mockResolvedValue(consent()),
      putConsent: vi.fn(),
      getStatus: vi.fn().mockResolvedValue(novelStatus()),
      rebuild: vi.fn(),
      cancel: vi.fn(),
      retryFailed: vi.fn(),
      clear: vi.fn(),
    };
    const harness = createReactHarness();
    const Component = createNovelSemanticIndexCard(harness.React, TEST_ANTD, api);
    let root = harness.render(Component, { novelId: TEST_NOVEL_ID });
    harness.commitEffects();
    await settle();
    root = harness.render(Component, { novelId: TEST_NOVEL_ID });

    const disclosure = findAll(
      root,
      (element) => element.type === "alert" && typeof element.props.description === "string",
    )[0].props.description as string;
    expect(disclosure).toContain("正式正文");
    expect(disclosure).toContain("正式大纲与故事设定");
    expect(disclosure).toContain("作者秘密");
    expect(disclosure).toContain("已绑定的私有素材");
    expect(findButton(root, "授权并允许后续索引").props.disabled).toBe(true);
  });


  it("does not couple authorization revocation to local vector cleanup", async () => {
    const granted = consent({
      state: "granted",
      consent_id: "33333333-3333-4333-8333-333333333333",
      version: 1,
      notice_version: "novel-embedding-consent/1",
      confirmed_at: "2026-08-29T09:00:00Z",
    });
    const status = novelStatus({
      state: "current",
      active_model_id: "qwen3.7-text-embedding",
      active_dimension: 1024,
      active_generation_number: 1,
      can_rebuild: true,
      has_local_vectors: true,
    });
    const putConsent = vi.fn<NovelSemanticIndexCardApi["putConsent"]>()
      .mockResolvedValue(consent({ state: "revoked", version: 2 }));
    const clear = vi.fn<NovelSemanticIndexCardApi["clear"]>().mockResolvedValue(
      novelStatus({ state: "empty", has_local_vectors: false }),
    );
    const api: NovelSemanticIndexCardApi = {
      getConsent: vi.fn().mockResolvedValue(granted),
      putConsent,
      getStatus: vi.fn().mockResolvedValue(status),
      rebuild: vi.fn(),
      cancel: vi.fn(),
      retryFailed: vi.fn(),
      clear,
    };
    const harness = createReactHarness();
    const Component = createNovelSemanticIndexCard(harness.React, TEST_ANTD, api);
    let root = harness.render(Component, { novelId: TEST_NOVEL_ID });
    harness.commitEffects();
    await settle();
    root = harness.render(Component, { novelId: TEST_NOVEL_ID });

    (findButton(root, "撤销云端授权").props.onClick as () => void)();
    root = harness.render(Component, { novelId: TEST_NOVEL_ID });
    expect(textContent(root)).toContain("不会自动删除 PostgreSQL 中已有的本地向量");
    expect(putConsent).not.toHaveBeenCalled();
    expect(clear).not.toHaveBeenCalled();

    (findButton(root, "确认撤销授权").props.onClick as () => void)();
    await settle();
    expect(putConsent).toHaveBeenCalledWith(
      TEST_NOVEL_ID,
      expect.objectContaining({ action: "revoke" }),
      expect.any(AbortSignal),
    );
    expect(clear).not.toHaveBeenCalled();
  });
});
