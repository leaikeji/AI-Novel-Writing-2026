import { describe, expect, it, vi } from "vitest";

import { toggleElementFullscreen } from "./relationship-fullscreen";


describe("toggleElementFullscreen", () => {
  it("enters fullscreen for the relationship canvas", async () => {
    const requestFullscreen = vi.fn(async () => undefined);
    const target = { requestFullscreen } as unknown as HTMLElement;
    const fullscreenDocument = {
      fullscreenElement: null,
      exitFullscreen: vi.fn(async () => undefined),
    } as unknown as Document;

    await expect(toggleElementFullscreen(target, fullscreenDocument)).resolves.toBe(true);
    expect(requestFullscreen).toHaveBeenCalledOnce();
    expect(fullscreenDocument.exitFullscreen).not.toHaveBeenCalled();
  });

  it("exits fullscreen when the relationship canvas is already fullscreen", async () => {
    const target = { requestFullscreen: vi.fn(async () => undefined) } as unknown as HTMLElement;
    const exitFullscreen = vi.fn(async () => undefined);
    const fullscreenDocument = {
      fullscreenElement: target,
      exitFullscreen,
    } as unknown as Document;

    await expect(toggleElementFullscreen(target, fullscreenDocument)).resolves.toBe(false);
    expect(exitFullscreen).toHaveBeenCalledOnce();
    expect(target.requestFullscreen).not.toHaveBeenCalled();
  });

  it("reports unsupported fullscreen instead of failing silently", async () => {
    const target = {} as HTMLElement;
    const fullscreenDocument = {
      fullscreenElement: null,
      exitFullscreen: vi.fn(async () => undefined),
    } as unknown as Document;

    await expect(toggleElementFullscreen(target, fullscreenDocument)).rejects.toThrow(
      "当前浏览器不支持全屏显示",
    );
  });
});
