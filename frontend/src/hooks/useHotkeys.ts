import { useEffect } from "react";

/** True when the keystroke belongs to whatever the operator is typing in. */
function typing(target: EventTarget | null): boolean {
  const el = target as HTMLElement | null;
  if (!el) return false;
  return (
    el.tagName === "INPUT" ||
    el.tagName === "TEXTAREA" ||
    el.tagName === "SELECT" ||
    el.isContentEditable
  );
}

export type Hotkeys = Record<string, (event: KeyboardEvent) => void>;

/** Bind shortcuts, ignoring keystrokes meant for a field.
 *
 * A key with a modifier — "mod+k" — is matched against ⌘ or Ctrl and is
 * allowed to fire while typing, because that is the point of it.
 */
export function useHotkeys(keys: Hotkeys, enabled = true): void {
  useEffect(() => {
    if (!enabled) return;

    const onKey = (event: KeyboardEvent) => {
      const mod = event.metaKey || event.ctrlKey;
      const handler = mod
        ? keys[`mod+${event.key.toLowerCase()}`]
        : (keys[event.key] ?? keys[event.key.toLowerCase()]);
      if (!handler) return;
      if (!mod && typing(event.target)) return;
      handler(event);
    };

    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [keys, enabled]);
}
