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
    const saveCandidate = vi.fn<EmbeddingConfigPageApi["saveCandidate"]>().mockResolvedValue(
      config({ api_key_masked: "********uest" }),
    );
    const api: EmbeddingConfigPageApi = {
      getConfig: vi.fn().mockResolvedValue(resource),
      initializeSecretStore: vi.fn(),
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
    expect(secretInput.props.defaultValue).toBe("");
    expect("value" in secretInput.props).toBe(false);
    expect(textContent(root)).toContain("只写保护");
    expect(textContent(root)).toContain("********cret");
    expect(findAll(root, (element) => element.type === "select")[0].props.value).toBe(2048);
    expect(findButton(root, "激活候选").props.disabled).toBe(true);

    const secretRef = secretInput.props.ref as {
      current: { input: { value: string } } | null;
    };
    secretRef.current = { input: { value: "short" } };
    (secretInput.props.onChange as (event: unknown) => void)({
      target: { value: "short" },
    });
    root = harness.render(Component, {});
    expect(textContent(root)).toContain("API Key 至少需要 16 个字符");
    expect(findButton(root, "验证并保存新 API Key").props.disabled).toBe(true);

    secretRef.current = { input: { value: "secret-only-in-request" } };
    const updatedSecretInput = findAll(
      root,
      (element) => element.props.type === "password",
    )[0];
    (updatedSecretInput.props.onChange as (event: unknown) => void)({
      target: { value: "secret-only-in-request" },
    });
    root = harness.render(Component, {});
    expect(textContent(root)).toContain("API Key 待验证");
    expect(textContent(root)).not.toContain("secret-only-in-request");
    expect(textContent(root)).not.toContain("-request");
    const save = findButton(root, "验证并保存新 API Key");
    (save.props.onClick as () => void)();
    await settle();
    root = harness.render(Component, {});

    expect(saveCandidate).toHaveBeenCalledWith(
      expect.objectContaining({
        expected_version: 7,
        api_key_action: "replace",
        api_key: "secret-only-in-request",
      }),
      expect.any(AbortSignal),
    );
    expect(secretRef.current.input.value).toBe("");
    expect(findAll(root, (element) => element.props.type === "password")[0].props.defaultValue)
      .toBe("");
    expect(textContent(root)).toContain("********uest");
    expect(textContent(root)).not.toContain("secret-only-in-request");
    expect(textContent(root)).not.toContain("-request");
  });

  it("requires the secret store and a key for the first connection", async () => {
    const resource = config({
      secret_store_ready: false,
      api_key_configured: false,
      api_key_masked: null,
      connection_state: "unconfigured",
      active_generation: null,
      candidate_generation: null,
    });
    const initializeSecretStore = vi.fn<
      EmbeddingConfigPageApi["initializeSecretStore"]
    >().mockResolvedValue(config({
      secret_store_ready: true,
      api_key_configured: false,
      api_key_masked: null,
      connection_state: "unconfigured",
      active_generation: null,
      candidate_generation: null,
    }));
    const api: EmbeddingConfigPageApi = {
      getConfig: vi.fn().mockResolvedValue(resource),
      initializeSecretStore,
      testConnection: vi.fn(),
      saveCandidate: vi.fn(),
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

    const secretAlerts = findAll(
      root,
      (element) => element.type === "alert"
        && element.props.message === "向量密钥保险箱尚未初始化",
    );
    expect(secretAlerts).toHaveLength(1);
    expect(findButton(root, "仅测试连接（不保存）").props.disabled).toBe(true);
    expect(findButton(root, "验证并保存配置").props.disabled).toBe(true);

    (findButton(secretAlerts[0].props.action, "本机恢复初始化").props.onClick as () => void)();
    await settle();
    root = harness.render(Component, {});
    expect(initializeSecretStore).toHaveBeenCalledWith(expect.any(AbortSignal));
    expect(textContent(root)).toContain("密钥保险箱正常");
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
