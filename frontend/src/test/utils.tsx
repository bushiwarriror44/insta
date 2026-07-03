import { screen, within } from "@testing-library/react";

/**
 * Finds the form control (`input`/`select`/`textarea`) immediately associated
 * with a `<label class="label">` element matching the given text.
 *
 * Works for the project's idiomatic field layout:
 *
 *   <div>
 *     <label class="label">Username</label>
 *     <input class="input" />
 *   </div>
 *
 * or with a wrapper div around the control. Avoids the need to manually wire
 * htmlFor/id on every form field.
 */
export function byLabel(
  label: string | RegExp,
  scope?: HTMLElement
): HTMLInputElement | HTMLSelectElement | HTMLTextAreaElement {
  const root = scope ? within(scope) : screen;
  const lbl = root.getByText(label, { selector: "label" });
  let cursor: Element | null = lbl.nextElementSibling;
  while (cursor) {
    if (
      cursor instanceof HTMLInputElement ||
      cursor instanceof HTMLSelectElement ||
      cursor instanceof HTMLTextAreaElement
    ) {
      return cursor;
    }
    const inner = cursor.querySelector("input, select, textarea");
    if (inner) {
      return inner as HTMLInputElement | HTMLSelectElement | HTMLTextAreaElement;
    }
    cursor = cursor.nextElementSibling;
  }
  throw new Error(`byLabel: no form control adjacent to "${label}"`);
}
