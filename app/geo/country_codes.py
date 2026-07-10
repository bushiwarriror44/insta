"""ISO country code normalization for proxy geo comparison."""
from __future__ import annotations

# Common operator-entered aliases → ISO-3166 alpha-2.
_COUNTRY_ALIASES: dict[str, str] = {
    "USA": "US",
    "UK": "GB",
    "UAE": "AE",
    "KSA": "SA",
    "RUSSIA": "RU",
    "GERMANY": "DE",
    "FRANCE": "FR",
    "SPAIN": "ES",
    "ITALY": "IT",
    "BRAZIL": "BR",
    "CANADA": "CA",
    "AUSTRALIA": "AU",
    "NETHERLANDS": "NL",
    "POLAND": "PL",
    "UKRAINE": "UA",
}

_SESSION_SOURCE_RU = {
    "database": "БД",
    "session_file": "файл",
    "none": "нет",
}


def normalize_country_code(code: str | None) -> str | None:
    """Return ISO-2 country code, mapping common aliases (e.g. USA → US)."""
    if not code:
        return None
    c = code.strip().upper()
    if not c:
        return None
    return _COUNTRY_ALIASES.get(c, c)


def countries_match(advertised: str | None, actual: str | None) -> bool:
    """True when both codes refer to the same country after normalization."""
    a = normalize_country_code(advertised)
    b = normalize_country_code(actual)
    if not a or not b:
        return True
    return a == b


def countries_mismatch(advertised: str | None, actual: str | None) -> bool:
    """True when both are set and differ after normalization."""
    a = normalize_country_code(advertised)
    b = normalize_country_code(actual)
    if not a or not b:
        return False
    return a != b
