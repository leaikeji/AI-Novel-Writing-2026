export interface OutlineCharacterReactRuntime {
  createElement(
    type: unknown,
    props?: Record<string, unknown> | null,
    ...children: unknown[]
  ): unknown;
}


export interface OutlineCharacterAntdRuntime {
  readonly Alert: unknown;
  readonly Button: unknown;
  readonly Card: unknown;
  readonly Input: unknown;
  readonly Select: unknown;
  readonly Tag: unknown;
}


export interface InputChangeEvent {
  readonly target: { readonly value: string };
}


export interface CheckedChangeEvent {
  readonly target: { readonly checked: boolean };
}
