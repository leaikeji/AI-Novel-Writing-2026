export interface PrivateLibraryReactRuntime {
  createElement(
    type: unknown,
    props?: Record<string, unknown> | null,
    ...children: unknown[]
  ): unknown;
  useState<T>(
    initial: T | (() => T),
  ): [T, (next: T | ((current: T) => T)) => void];
  useRef<T>(initial: T): { current: T };
  useEffect(effect: () => void | (() => void), dependencies: readonly unknown[]): void;
}


export interface PrivateLibraryInputComponent {
  readonly TextArea: unknown;
}


export interface PrivateLibraryAntdRuntime {
  readonly Alert: unknown;
  readonly Button: unknown;
  readonly Card: unknown;
  readonly Drawer: unknown;
  readonly Empty: unknown;
  readonly Input: PrivateLibraryInputComponent;
  readonly Select: unknown;
  readonly Spin: unknown;
  readonly Switch: unknown;
  readonly Tag: unknown;
}


export interface FocusHandle {
  focus(): void;
}


export interface InputChangeEvent {
  readonly target: { readonly value: string };
}


export interface KeyboardEventLike {
  readonly key: string;
  preventDefault(): void;
}
