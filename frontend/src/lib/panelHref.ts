const APP_SEGMENTS = new Set([
  "accounts",
  "publishing",
  "agent",
  "renders",
  "activity",
  "operators",
  "settings",
  "calendar",
  "maintenance",
  "login",
]);

/** Panel path without the secret gate prefix, e.g. `/accounts`. */
export function panelPath(pathname = window.location.pathname): string {
  const parts = pathname.split("/").filter(Boolean);
  if (parts[0] && !APP_SEGMENTS.has(parts[0])) {
    parts.shift();
  }
  if (!parts.length) return "/";
  return `/${parts.join("/")}`;
}

/** Full URL for a panel path, including the secret gate prefix. */
export function panelHref(path: string): string {
  const origin = window.location.origin;
  const parts = window.location.pathname.split("/").filter(Boolean);
  let prefix = "";
  if (parts[0] && !APP_SEGMENTS.has(parts[0])) {
    prefix = `/${parts[0]}`;
  }
  const rel = path.startsWith("/") ? path : `/${path}`;
  return `${origin}${prefix}${rel}`;
}
