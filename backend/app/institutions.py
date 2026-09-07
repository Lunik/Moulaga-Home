"""Canonical institutions and compatibility for legacy combined bank names."""

from __future__ import annotations

import re
import unicodedata

UNASSIGNED_INSTITUTION = "Établissement non renseigné"

_INSTITUTION_ALIASES: dict[str, tuple[str, ...]] = {
    "ABN AMRO": (),
    "Amundi": (),
    "Banca Intesa Sanpaolo": (),
    "Banco Santander": (),
    "Bank of Ireland": (),
    "Banque Populaire": (),
    "Barclays": (),
    "BBVA": (),
    "BNP Paribas": (),
    "Boursobank": ("Bourso Bank", "Boursorama", "Boursorama Banque"),
    "Caisse d’Épargne": (),
    "CIC": (),
    "Commerzbank": (),
    "Crédit Agricole": (),
    "Crédit Mutuel": (),
    "Danske Bank": (),
    "Deutsche Bank": (),
    "Fortuneo": (),
    "Hello bank!": (),
    "HSBC": (),
    "ING": (),
    "KBC": (),
    "La Banque Postale": (),
    "LCL": (),
    "Lloyds Bank": (),
    "Monabanq": (),
    "N26": (),
    "NatWest": (),
    "Raiffeisen Bank": (),
    "Revolut": (),
    "Société Générale": (),
    "Trade Republic": (),
    "UniCredit": (),
    "Volkswagen Bank": (),
    "Wise": (),
}


def _search_key(value: str) -> str:
    decomposed = unicodedata.normalize("NFKD", value)
    without_accents = "".join(
        character
        for character in decomposed
        if not unicodedata.combining(character)
    )
    return re.sub(r"[^a-z0-9]+", " ", without_accents.casefold()).strip()


_GROUP_PREFIXES = tuple(
    (
        group,
        tuple(
            sorted(
                {
                    _search_key(group),
                    *(_search_key(alias) for alias in aliases),
                },
                key=len,
                reverse=True,
            )
        ),
    )
    for group, aliases in _INSTITUTION_ALIASES.items()
)


def _clean_optional(value: str | None) -> str | None:
    if value is None:
        return None
    cleaned = " ".join(value.split())
    return cleaned or None


def _matching_group(institution: str) -> tuple[str, str] | None:
    search_key = _search_key(institution)
    for group, prefixes in _GROUP_PREFIXES:
        for prefix in prefixes:
            if search_key == prefix or search_key.startswith(f"{prefix} "):
                return group, prefix
    return None


def institution_group(institution: str | None) -> str | None:
    """Map an institution, including legacy combined names, to its group."""
    cleaned = _clean_optional(institution)
    if cleaned is None:
        return None
    match = _matching_group(cleaned)
    return match[0] if match is not None else cleaned


def institution_fields(
    institution: str | None,
    regional_entity: str | None,
) -> dict[str, str | None]:
    """Normalize the institution and extract legacy regional suffixes."""
    cleaned_institution = _clean_optional(institution)
    cleaned_regional_entity = _clean_optional(regional_entity)
    if cleaned_institution is None:
        return {"institution": None, "regional_entity": None}

    match = _matching_group(cleaned_institution)
    if match is None:
        return {
            "institution": cleaned_institution,
            "regional_entity": cleaned_regional_entity,
        }

    group, prefix = match
    if cleaned_regional_entity is not None:
        return {
            "institution": group,
            "regional_entity": cleaned_regional_entity,
        }

    tokens = list(re.finditer(r"[0-9A-Za-zÀ-ÖØ-öø-ÿ]+", cleaned_institution))
    prefix_token_count = len(prefix.split())
    extracted = None
    if len(tokens) > prefix_token_count:
        extracted = cleaned_institution[tokens[prefix_token_count].start() :].lstrip(
            " -–—·:/"
        )
    return {
        "institution": group,
        "regional_entity": extracted or None,
    }


def institution_label(
    institution: str | None,
    regional_entity: str | None,
) -> str | None:
    """Return the distinct display and grouping label for an institution."""
    fields = institution_fields(institution, regional_entity)
    normalized_institution = fields["institution"]
    if normalized_institution is None:
        return None
    normalized_regional_entity = fields["regional_entity"]
    if normalized_regional_entity is None:
        return normalized_institution
    return f"{normalized_institution} · {normalized_regional_entity}"
