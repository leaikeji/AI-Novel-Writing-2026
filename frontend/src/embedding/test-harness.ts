import type { EmbeddingAntdRuntime, EmbeddingReactRuntime } from "./ui-runtime";


export interface FakeElement {
  readonly type: unknown;
  readonly props: Record<string, unknown>;
  readonly children: readonly unknown[];
}


interface EffectRecord {
  dependencies: readonly unknown[];
  cleanup?: () => void;
}


function sameDependencies(
  left: readonly unknown[] | undefined,
  right: readonly unknown[],
): boolean {
  return Boolean(left
    && left.length === right.length
    && left.every((item, index) => Object.is(item, right[index])));
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


export const TEST_ANTD: EmbeddingAntdRuntime = {
  Alert: "alert",
  Button: "button",
  Card: "article",
  Empty: "empty",
  Input: "input",
  InputNumber: "input-number",
  Select: "select",
  Spin: "spin",
  Tag: "tag",
};


export function createReactHarness() {
  const states: unknown[] = [];
  const refs: Array<{ current: unknown }> = [];
  const effects: Array<EffectRecord | undefined> = [];
  let pendingEffects: Array<{
    index: number;
    effect: () => void | (() => void);
    dependencies: readonly unknown[];
  }> = [];
  let stateIndex = 0;
  let refIndex = 0;
  let effectIndex = 0;

  const React: EmbeddingReactRuntime = {
    createElement(type, props, ...children): FakeElement {
      return { type, props: props ?? {}, children };
    },
    useState<T>(initial: T | (() => T)): [T, (next: T | ((current: T) => T)) => void] {
      const index = stateIndex++;
      if (!(index in states)) {
        states[index] = typeof initial === "function" ? (initial as () => T)() : initial;
      }
      return [
        states[index] as T,
        (next) => {
          states[index] = typeof next === "function"
            ? (next as (current: T) => T)(states[index] as T)
            : next;
        },
      ];
    },
    useRef<T>(initial: T): { current: T } {
      const index = refIndex++;
      if (!refs[index]) refs[index] = { current: initial };
      return refs[index] as { current: T };
    },
    useEffect(effect, dependencies): void {
      const index = effectIndex++;
      if (sameDependencies(effects[index]?.dependencies, dependencies)) return;
      pendingEffects.push({ index, effect, dependencies: [...dependencies] });
    },
  };

  return {
    React,
    render<Props>(Component: (props: Props) => unknown, props: Props): FakeElement {
      stateIndex = 0;
      refIndex = 0;
      effectIndex = 0;
      pendingEffects = [];
      return Component(props) as FakeElement;
    },
    commitEffects(): void {
      const pending = pendingEffects;
      pendingEffects = [];
      pending.forEach((item) => {
        effects[item.index]?.cleanup?.();
        const cleanup = item.effect();
        effects[item.index] = {
          dependencies: item.dependencies,
          cleanup: typeof cleanup === "function" ? cleanup : undefined,
        };
      });
    },
  };
}


export async function settle(): Promise<void> {
  await Promise.resolve();
  await Promise.resolve();
  await Promise.resolve();
}
