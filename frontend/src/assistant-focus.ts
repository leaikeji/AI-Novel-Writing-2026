export interface FocusableDialogTrigger {
  focus(options?: FocusOptions): void;
}


export function restoreDialogTriggerFocus(
  trigger: FocusableDialogTrigger | null | undefined,
): boolean {
  if (!trigger) return false;
  trigger.focus({ preventScroll: true });
  return true;
}
