export type DocSpan = string | { text: string; href: string };

export function apiLink(text: string): DocSpan {
  return { text, href: "#api" };
}
