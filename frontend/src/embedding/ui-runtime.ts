export interface EmbeddingReactRuntime {
  createElement(
    type: unknown,
    props?: Record<string, unknown> | null,
    ...children: unknown[]
  ): unknown;
  useState<T>(
    initial: T | (() => T),
  ): [T, (next: T | ((current: T) => T)) => void];
  useRef<T>(initial: T): { current: T };
  useEffect(
    effect: () => void | (() => void),
    dependencies: readonly unknown[],
  ): void;
}


export interface EmbeddingAntdRuntime {
  readonly Alert: unknown;
  readonly Button: unknown;
  readonly Card: unknown;
  readonly Empty: unknown;
  readonly Input: unknown;
  readonly InputNumber: unknown;
  readonly Select: unknown;
  readonly Spin: unknown;
  readonly Tag: unknown;
}


export interface InputChangeEvent {
  readonly target: { readonly value: string };
}


export interface CheckedChangeEvent {
  readonly target: { readonly checked: boolean };
}


export interface FocusableElement {
  focus(options?: FocusOptions): void;
}
