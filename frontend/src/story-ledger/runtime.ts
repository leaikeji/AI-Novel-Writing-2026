export type StoryLedgerElementNode = unknown;

/** Minimal structural React surface used by host-provided React. */
export interface StoryLedgerReactRuntime {
  createElement(
    type: unknown,
    props?: Record<string, unknown> | null,
    ...children: unknown[]
  ): StoryLedgerElementNode;
}
