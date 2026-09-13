import type { LibraryCheckHitRecord } from "../types";
import type { PrivateLibraryReactRuntime } from "./ui-runtime";

export type CandidateHitLocator = (hit: LibraryCheckHitRecord) => void;

export interface CandidateSourcePreviewProps {
  text: string;
  bindLocator: (locate: CandidateHitLocator | null) => void;
}

/** Plain text only: locating a report hit must never edit or interpret author text. */
export function createCandidateSourcePreview(React: PrivateLibraryReactRuntime) {
  const h = React.createElement;
  return function CandidateSourcePreview(props: CandidateSourcePreviewProps): unknown {
    const [located, setLocated] = React.useState<LibraryCheckHitRecord | null>(null);
    const valid = located !== null && Number.isInteger(located.start_utf16)
      && Number.isInteger(located.end_utf16) && located.start_utf16 >= 0
      && located.end_utf16 > located.start_utf16 && located.end_utf16 <= props.text.length
      && props.text.slice(located.start_utf16, located.end_utf16) === located.matched_text;
    return h("section", null,
      h("p", null, "本次拟采用正文（只读；使用“定位原句”查看具体命中）"),
      h("div", {
        role: "region", "aria-label": "本次拟采用正文", tabIndex: 0,
        style: { whiteSpace: "pre-wrap", overflowWrap: "anywhere", overflow: "auto",
          maxHeight: "min(220px, 25vh)", minHeight: 110, padding: 8, border: "1px solid currentColor" },
        ref: (node: HTMLElement | null) => {
          props.bindLocator(node ? (hit) => setLocated({ ...hit }) : null);
        },
      }, ...(valid && located ? [
        props.text.slice(0, located.start_utf16),
        h("mark", {
          tabIndex: -1, "aria-label": `当前命中：${located.matched_text}`,
          ref: (node: HTMLElement | null) => {
            if (!node) return;
            node.focus({ preventScroll: true });
            node.scrollIntoView({ block: "nearest", inline: "nearest" });
          },
        }, props.text.slice(located.start_utf16, located.end_utf16)),
        props.text.slice(located.end_utf16),
      ] : [props.text])),
    );
  };
}
