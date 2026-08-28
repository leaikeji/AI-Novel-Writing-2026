import { describe, expect, it } from "vitest";

import { createNovelCoverView, isTextNovelCover } from "./novel-cover";


const React = {
  createElement(type: unknown, props: Record<string, unknown> | null, ...children: unknown[]) {
    return { type, props: { ...(props || {}), children } };
  },
};


describe("novel cover", () => {
  it("renders title and author as accessible text without an image source", () => {
    const NovelCoverView = createNovelCoverView(React);
    const rendered = NovelCoverView({
      novel: {
        title: "雾港来信",
        author_name: "林舟",
        cover_mode: "text",
        cover_image_data: "",
      },
      className: "cover",
      fallbackSrc: "fallback.jpg",
    }) as any;

    expect(isTextNovelCover({ cover_mode: "text" })).toBe(true);
    expect(rendered.type).toBe("div");
    expect(rendered.props.role).toBe("img");
    expect(rendered.props["aria-label"]).toBe("雾港来信，林舟著，文字封面");
    expect(rendered.props.children.map((child: any) => child.props.children).flat()).toEqual([
      "长篇小说",
      "雾港来信",
      "林舟 著",
    ]);
  });

  it("keeps image covers on the existing image path", () => {
    const NovelCoverView = createNovelCoverView(React);
    const rendered = NovelCoverView({
      novel: {
        title: "雾港来信",
        author_name: "林舟",
        cover_mode: "upload",
        cover_image_data: "data:image/jpeg;base64,AA==",
      },
      className: "cover",
      fallbackSrc: "fallback.jpg",
    }) as any;

    expect(rendered.type).toBe("img");
    expect(rendered.props.src).toBe("data:image/jpeg;base64,AA==");
  });
});
