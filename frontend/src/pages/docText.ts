export type DocSpan = string | { text: string; href: string };

export function apiLink(text: string): DocSpan {
  return { text, href: "#api" };
}

export function connectionsLink(text: string): DocSpan {
  return { text, href: "#connections" };
}
