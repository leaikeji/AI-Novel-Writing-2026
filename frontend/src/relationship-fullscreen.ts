export async function toggleElementFullscreen(
  target: HTMLElement,
  fullscreenDocument: Document = document,
): Promise<boolean> {
  if (fullscreenDocument.fullscreenElement === target) {
    if (typeof fullscreenDocument.exitFullscreen !== "function") {
      throw new Error("当前浏览器不支持退出全屏");
    }
    await fullscreenDocument.exitFullscreen();
    return false;
  }

  if (typeof target.requestFullscreen !== "function") {
    throw new Error("当前浏览器不支持全屏显示");
  }
  if (fullscreenDocument.fullscreenElement) {
    await fullscreenDocument.exitFullscreen();
  }
  await target.requestFullscreen();
  return true;
}
