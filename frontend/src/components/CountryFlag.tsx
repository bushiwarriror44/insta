/** ISO-3166 alpha-2 country code to flag emoji (no external deps). */
export function countryCodeToFlag(code: string | null | undefined): string | null {
  if (!code) return null;
  const normalized = code.trim().toUpperCase();
  if (!/^[A-Z]{2}$/.test(normalized)) return null;
  const base = 0x1f1e6;
  return String.fromCodePoint(
    ...[...normalized].map((ch) => base + ch.charCodeAt(0) - 65)
  );
}

interface CountryFlagProps {
  code: string | null | undefined;
  className?: string;
  showCode?: boolean;
}

export function CountryFlag({ code, className = "", showCode = false }: CountryFlagProps) {
  const flag = countryCodeToFlag(code);
  if (!flag) {
    return <span className={`text-slate-500 ${className}`.trim()}>—</span>;
  }
  const label = (code ?? "").trim().toUpperCase();
  return (
    <span className={`inline-flex items-center gap-1 ${className}`.trim()} title={label}>
      <span aria-hidden="true">{flag}</span>
      {showCode ? <span className="text-xs text-slate-400">{label}</span> : null}
    </span>
  );
}
