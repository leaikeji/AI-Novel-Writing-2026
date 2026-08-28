import type { NovelCoverMode } from "./types";


export interface NovelCoverDescriptor {
  title: string;
  author_name: string;
  cover_mode: NovelCoverMode;
  cover_image_data: string;
}


export interface NovelCoverViewProps {
  novel: NovelCoverDescriptor;
  className: string;
  fallbackSrc: string;
}


export function isTextNovelCover(novel: Pick<NovelCoverDescriptor, "cover_mode">): boolean {
  return novel.cover_mode === "text";
}


export function createNovelCoverView(React: any) {
  const h = React.createElement;

  return function NovelCoverView(props: NovelCoverViewProps): unknown {
    const { novel } = props;
    if (!isTextNovelCover(novel)) {
      return h("img", {
        className: props.className,
        src: novel.cover_image_data || props.fallbackSrc,
        alt: `${novel.title}封面`,
      });
    }

    return h(
      "div",
      {
        className: `${props.className} anw-text-cover`,
        role: "img",
        "aria-label": `${novel.title}，${novel.author_name}著，文字封面`,
      },
      h("span", { className: "anw-text-cover-kicker", "aria-hidden": "true" }, "长篇小说"),
      h("strong", { className: "anw-text-cover-title" }, novel.title || "未命名小说"),
      h("span", { className: "anw-text-cover-author" }, `${novel.author_name || "佚名"} 著`),
    );
  };
}
