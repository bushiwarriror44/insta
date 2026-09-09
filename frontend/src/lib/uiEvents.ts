export const SHOW_ASSISTANT = "panel-show-assistant";
export const FOCUS_PAGE_SEARCH = "panel-focus-search";
export const REFRESH_NAV_BADGES = "panel-refresh-nav-badges";

export function showAssistant() {
  window.dispatchEvent(new Event(SHOW_ASSISTANT));
}

export function refreshNavBadges() {
  window.dispatchEvent(new Event(REFRESH_NAV_BADGES));
}

export function focusPageSearch() {
  const field = document.querySelector<HTMLInputElement>("[data-page-search]");
  if (field) {
    field.focus();
    field.select();
    return true;
  }
  return false;
}
