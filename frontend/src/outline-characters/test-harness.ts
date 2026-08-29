import type {
  OutlineCharacterAntdRuntime,
  OutlineCharacterReactRuntime,
} from "./ui-runtime";


export interface FakeElement {
  readonly type: unknown;
  readonly props: Record<string, unknown>;
  readonly children: readonly unknown[];
}


export function isElement(value: unknown): value is FakeElement {
  return typeof value === "object" && value !== null && "type" in value && "props" in value;
}


export function textContent(root: unknown): string {
  if (typeof root === "string" || typeof root === "number") return String(root);
  if (Array.isArray(root)) return root.map(textContent).join("");
  if (!isElement(root)) return "";
  return root.children.map(textContent).join("");
}


export function findAll(
  root: unknown,
  predicate: (element: FakeElement) => boolean,
): FakeElement[] {
  if (Array.isArray(root)) return root.flatMap((child) => findAll(child, predicate));
  if (!isElement(root)) return [];
  return [
    ...(predicate(root) ? [root] : []),
    ...root.children.flatMap((child) => findAll(child, predicate)),
  ];
}


export function findButton(root: unknown, label: string): FakeElement {
  const button = findAll(
    root,
    (element) => element.type === "button" && textContent(element) === label,
  )[0];
  if (!button) throw new Error(`button not found: ${label}`);
  return button;
}


export const TEST_REACT: OutlineCharacterReactRuntime = {
  createElement(type, props, ...children): FakeElement {
    return { type, props: props ?? {}, children };
  },
};


export const TEST_ANTD: OutlineCharacterAntdRuntime = {
  Alert: "alert",
  Button: "button",
  Card: "article",
  Input: "input",
  Select: "select",
  Tag: "tag",
};
