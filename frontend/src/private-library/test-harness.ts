import type {
  PrivateLibraryAntdRuntime,
  PrivateLibraryReactRuntime,
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


export function findByLabel(root: unknown, label: string): FakeElement {
  const result = findAll(root, (element) => element.props["aria-label"] === label)[0];
  if (!result) throw new Error(`element not found by label: ${label}`);
  return result;
}


export function findButton(root: unknown, label: string): FakeElement {
  const result = findAll(root, (element) => (
    element.type === "button" && textContent(element) === label
  ))[0];
  if (!result) throw new Error(`button not found: ${label}`);
  return result;
}


export function createPrivateLibraryHarness() {
  const states: Array<{ value: unknown }> = [];
  const refs: Array<{ current: unknown }> = [];
  let stateIndex = 0;
  let refIndex = 0;
  const React: PrivateLibraryReactRuntime = {
    createElement(type, props, ...children): FakeElement {
      return { type, props: props ?? {}, children };
    },
    useState<T>(initial: T | (() => T)): [T, (next: T | ((current: T) => T)) => void] {
      const index = stateIndex++;
      if (!states[index]) {
        states[index] = { value: typeof initial === "function" ? (initial as () => T)() : initial };
      }
      return [states[index].value as T, (next) => {
        const current = states[index]!.value as T;
        states[index]!.value = typeof next === "function"
          ? (next as (value: T) => T)(current)
          : next;
      }];
    },
    useRef<T>(initial: T): { current: T } {
      const index = refIndex++;
      if (!refs[index]) refs[index] = { current: initial };
      return refs[index] as { current: T };
    },
    useEffect(): void {
      // Component tests exercise deterministic render and event behavior only.
    },
  };
  return {
    React,
    render<Props>(Component: (props: Props) => unknown, props: Props): FakeElement {
      stateIndex = 0;
      refIndex = 0;
      return Component(props) as FakeElement;
    },
  };
}


const Input = Object.assign("input", { TextArea: "textarea" });


export const TEST_ANTD: PrivateLibraryAntdRuntime = {
  Alert: "alert",
  Button: "button",
  Card: "article",
  Drawer: "drawer",
  Empty: "empty",
  Input,
  Select: "select",
  Spin: "spin",
  Switch: "switch",
  Tag: "tag",
};
