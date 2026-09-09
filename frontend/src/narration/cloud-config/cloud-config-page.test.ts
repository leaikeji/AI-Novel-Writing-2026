import { describe, expect, it, vi } from "vitest";

import {
  createTtsCloudConfigPage,
  type TtsCloudConfigPageApi,
} from "./cloud-config-page";
import { cloudProfile, cloudProfiles, cloudTestResponse } from "./test-fixtures";
import {
  TEST_ANTD,
  createReactHarness,
  findAll,
  findButton,
  settle,
  textContent,
} from "./test-harness";


function pageApi(patch: Partial<TtsCloudConfigPageApi> = {}): TtsCloudConfigPageApi {
  return {
    getProfiles: vi.fn().mockResolvedValue(cloudProfiles()),
    createProfile: vi.fn(),
    updateProfile: vi.fn(),
    testProfile: vi.fn(),
    activateProfile: vi.fn(),
    disableProfile: vi.fn(),
    deleteProfile: vi.fn(),
    ...patch,
  };
}


async function renderReady(api: TtsCloudConfigPageApi) {
  const harness = createReactHarness();
  const Component = createTtsCloudConfigPage(harness.React, TEST_ANTD, api);
  let root = harness.render(Component, {});
  harness.commitEffects();
  await settle();
  root = harness.render(Component, {});
  return { harness, Component, root };
}


describe("TTS cloud configuration page", () => {
  it("renders a useful empty state and a recoverable load error", async () => {
    const empty = await renderReady(pageApi({
      getProfiles: vi.fn().mockResolvedValue(cloudProfiles({ items: [] })),
    }));
    expect(findAll(
      empty.root,
      (element) => element.type === "empty"
        && element.props.description === "尚未配置云端语音渠道",
    )).toHaveLength(1);
    expect(findButton(empty.root, "新增渠道").props.type).toBe("primary");

    const retry = vi.fn().mockResolvedValue(cloudProfiles({ items: [] }));
    const failedApi = pageApi({ getProfiles: vi.fn().mockRejectedValueOnce(new Error("网络断开")).mockImplementation(retry) });
    const harness = createReactHarness();
    const Component = createTtsCloudConfigPage(harness.React, TEST_ANTD, failedApi);
    let root = harness.render(Component, {});
    harness.commitEffects();
    await settle();
    root = harness.render(Component, {});
    const loadAlerts = findAll(
      root,
      (element) => element.type === "alert"
        && element.props.message === "无法加载语音模型接入页",
    );
    expect(loadAlerts).toHaveLength(1);
    (findButton(loadAlerts[0].props.action, "重新加载").props.onClick as () => void)();
    await settle();
    root = harness.render(Component, {});
    expect(findAll(
      root,
      (element) => element.type === "empty"
        && element.props.description === "尚未配置云端语音渠道",
    )).toHaveLength(1);
  });

  it("keeps the API key write-only and saving never starts a model test", async () => {
    const created = cloudProfiles({ items: [cloudProfile({ name: "新渠道" })] });
    const createProfile = vi.fn<TtsCloudConfigPageApi["createProfile"]>().mockResolvedValue(created);
    const testProfile = vi.fn<TtsCloudConfigPageApi["testProfile"]>();
    const api = pageApi({
      getProfiles: vi.fn().mockResolvedValue(cloudProfiles({ items: [] })),
      createProfile,
      testProfile,
    });
    const rendered = await renderReady(api);
    let root = rendered.root;
    (findButton(root, "新增渠道").props.onClick as () => void)();
    root = rendered.harness.render(rendered.Component, {});

    const inputs = findAll(root, (element) => element.type === "input");
    expect(inputs).toHaveLength(5);
    const values = ["新渠道", "https://voice.example.com/custom", "quality-model", "speed-model"];
    inputs.slice(0, 4).forEach((input, index) => {
      (input.props.onChange as (event: unknown) => void)({ target: { value: values[index] } });
    });
    const password = inputs[4];
    expect(password.props.defaultValue).toBe("");
    expect("value" in password.props).toBe(false);
    const passwordRef = password.props.ref as { current: { input: { value: string } } | null };
    passwordRef.current = { input: { value: "secret-write-only" } };
    (password.props.onChange as (event: unknown) => void)({ target: { value: "secret-write-only" } });
    root = rendered.harness.render(rendered.Component, {});
    expect(textContent(root)).not.toContain("secret-write-only");

    (findButton(root, "保存配置（不测试）").props.onClick as () => void)();
    await settle();
    root = rendered.harness.render(rendered.Component, {});
    expect(createProfile).toHaveBeenCalledWith(
      expect.objectContaining({
        api_key: "secret-write-only",
        base_url: "https://voice.example.com/custom",
        expected_version: 0,
      }),
      expect.any(AbortSignal),
    );
    expect(testProfile).not.toHaveBeenCalled();
    expect(textContent(root)).not.toContain("secret-write-only");
    expect(textContent(root)).toContain("尚未发起任何付费测试");
  });

  it("adds HTTPS to a host-only Base URL without duplicating an existing scheme", async () => {
    const createProfile = vi.fn<TtsCloudConfigPageApi["createProfile"]>().mockResolvedValue(
      cloudProfiles({ items: [cloudProfile()] }),
    );
    const rendered = await renderReady(pageApi({
      getProfiles: vi.fn().mockResolvedValue(cloudProfiles({ items: [] })),
      createProfile,
    }));
    let root = rendered.root;
    (findButton(root, "新增渠道").props.onClick as () => void)();
    root = rendered.harness.render(rendered.Component, {});

    const inputs = findAll(root, (element) => element.type === "input");
    (inputs[0].props.onChange as (event: unknown) => void)({ target: { value: "阿里云" } });
    (inputs[1].props.onChange as (event: unknown) => void)({
      target: { value: "workspace.cn-beijing.maas.aliyuncs.com" },
    });
    (inputs[2].props.onChange as (event: unknown) => void)({
      target: { value: "qwen-audio-3.0-tts-plus" },
    });
    root = rendered.harness.render(rendered.Component, {});
    (findButton(root, "保存配置（不测试）").props.onClick as () => void)();
    await settle();

    expect(createProfile).toHaveBeenCalledWith(
      expect.objectContaining({
        base_url: "https://workspace.cn-beijing.maas.aliyuncs.com",
      }),
      expect.any(AbortSignal),
    );
  });

  it("requires an explicit billing acknowledgement before testing", async () => {
    const testProfile = vi.fn<TtsCloudConfigPageApi["testProfile"]>().mockResolvedValue(
      cloudTestResponse(),
    );
    const api = pageApi({ testProfile });
    const rendered = await renderReady(api);
    let root = rendered.root;

    (findButton(root, "测试质量模型").props.onClick as () => void)();
    root = rendered.harness.render(rendered.Component, {});
    const dialog = findAll(root, (element) => element.props.role === "alertdialog")[0];
    expect(dialog.props.tabIndex).toBe(-1);
    expect(textContent(dialog)).toContain("可能产生一次云端调用费用");
    expect(findButton(dialog, "确认计费并测试").props.disabled).toBe(true);
    expect(testProfile).not.toHaveBeenCalled();

    const checkbox = findAll(dialog, (element) => element.type === "checkbox")[0];
    (checkbox.props.onChange as (event: unknown) => void)({ target: { checked: true } });
    root = rendered.harness.render(rendered.Component, {});
    (findButton(root, "确认计费并测试").props.onClick as () => void)();
    await settle();

    expect(testProfile).toHaveBeenCalledWith(
      cloudProfile().id,
      expect.objectContaining({
        expected_version: 3,
        slot: "quality",
        billing_confirmed: true,
      }),
      expect.any(AbortSignal),
    );
  });

  it("requires a separate confirmation before activating a verified channel", async () => {
    const active = cloudProfile({ lifecycle_state: "active", version: 4 });
    const activatedResource = cloudProfiles({ items: [active], active_profile_id: active.id });
    const activateProfile = vi.fn<TtsCloudConfigPageApi["activateProfile"]>().mockResolvedValue(
      activatedResource,
    );
    const api = pageApi({ activateProfile });
    const rendered = await renderReady(api);
    let root = rendered.root;

    (findButton(root, "启用").props.onClick as () => void)();
    expect(activateProfile).not.toHaveBeenCalled();
    root = rendered.harness.render(rendered.Component, {});
    expect(textContent(root)).toContain("确认启用渠道");
    const confirm = findButton(root, "确认操作");
    expect(confirm.props.type).toBe("primary");
    (confirm.props.onClick as () => void)();
    await settle();
    expect(activateProfile).toHaveBeenCalledWith(
      cloudProfile().id,
      expect.objectContaining({ expected_version: 3 }),
      expect.any(AbortSignal),
    );
  });

  it("uses keyboard-native buttons for every page action", async () => {
    const rendered = await renderReady(pageApi());
    const buttons = findAll(rendered.root, (element) => element.type === "button");
    expect(buttons.length).toBeGreaterThan(4);
    expect(buttons.every((button) => button.props.htmlType === "button"))
      .toBe(true);
    expect(findAll(
      rendered.root,
      (element) => element.type !== "button" && typeof element.props.onClick === "function",
    )).toHaveLength(0);
  });
});
