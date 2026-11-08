"""Deterministic evaluation against manually annotated funding articles."""

from __future__ import annotations

import json
import math


FIELDS = {"name", "hq_country", "sector", "round", "amount_usd", "lead_investors", "evidence"}
ROUNDS = {"Pre-seed", "Seed", "Series A", "Series B", "Series C+", "Unknown"}
WEIGHTS = {"hq_country": 1, "sector": 1, "round": 2, "amount_usd": 3,
           "lead_investors": 2, "evidence": 2}


def normalize(value):
    return " ".join(value.split()).casefold()


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"Duplicate JSON key: {key}")
        result[key] = value
    return result


def reject_constant(value):
    raise ValueError(f"Nonfinite JSON number: {value}")


def nonempty(value):
    return isinstance(value, str) and bool(value.strip())


def validate(raw, article):
    try:
        value = json.loads(raw, object_pairs_hook=unique_object, parse_constant=reject_constant)
    except (ValueError, TypeError) as exc:
        return None, [f"Invalid JSON: {exc}"]
    if not isinstance(value, dict) or set(value) != {"companies"}:
        return None, ["Top-level JSON must contain only companies"]
    companies = value["companies"]
    if not isinstance(companies, list):
        return None, ["companies must be an array"]
    errors, names = [], set()
    for index, company in enumerate(companies):
        prefix = f"companies[{index}]"
        if not isinstance(company, dict) or set(company) != FIELDS:
            errors.append(f"{prefix}: exactly the seven required fields must be present")
            continue
        if not nonempty(company["name"]):
            errors.append(f"{prefix}: name must be a nonempty string")
        else:
            name = normalize(company["name"])
            if name in names:
                errors.append(f"{prefix}: duplicate company name")
            names.add(name)
        for field in ["hq_country", "sector"]:
            if company[field] is not None and not nonempty(company[field]):
                errors.append(f"{prefix}: {field} must be a nonempty string or null")
        if not isinstance(company["round"], str) or company["round"] not in ROUNDS:
            errors.append(f"{prefix}: invalid round enum")
        amount = company["amount_usd"]
        if amount is not None and (isinstance(amount, bool)
                                   or not isinstance(amount, (int, float))
                                   or isinstance(amount, float) and not math.isfinite(amount)
                                   or amount < 0):
            errors.append(f"{prefix}: amount_usd must be a finite nonnegative number or null")
        leads = company["lead_investors"]
        if not isinstance(leads, list) or not all(nonempty(lead) for lead in leads):
            errors.append(f"{prefix}: lead_investors must be an array of nonempty strings")
        elif len({normalize(lead) for lead in leads}) != len(leads):
            errors.append(f"{prefix}: duplicate lead investor")
        evidence = company["evidence"]
        if not nonempty(evidence) or len(evidence) > 300:
            errors.append(f"{prefix}: evidence must be a nonempty quote of at most 300 characters")
        elif evidence not in article:
            errors.append(f"{prefix}: evidence must be a verbatim contiguous article substring")
    return (value if not errors else None), errors


def evaluate_output(raw: str, case: dict) -> dict:
    value, errors = validate(raw, case["article"])
    if value is None:
        return {"score": 0.0, "schema_valid": False, "exact": False, "errors": errors}
    predicted = {normalize(company["name"]): company for company in value["companies"]}
    expected = {normalize(company["name"]): company for company in case["expected"]}
    if not expected:
        exact = not predicted
        return {"score": 1.0 if exact else 0.0, "schema_valid": True, "exact": exact,
                "errors": [] if exact else ["No new financing is announced; companies must be empty"]}
    missing, extra = expected.keys() - predicted.keys(), predicted.keys() - expected.keys()
    errors.extend(f"Missing company: {expected[name]['name']}" for name in sorted(missing))
    errors.extend(f"Unexpected company: {predicted[name]['name']}" for name in sorted(extra))
    points = 0
    for name in sorted(expected.keys() & predicted.keys()):
        gold, actual = expected[name], predicted[name]
        points += 2
        for field, weight in WEIGHTS.items():
            if field == "evidence":
                matches = all(any(term in actual[field] for term in group)
                              for group in gold.get("evidence_terms", []))
                expected_display = gold.get("evidence_terms", [])
            elif field == "sector":
                options = [gold[field], *gold.get("sector_aliases", [])]
                matches = any(actual[field] is None and option is None
                              or isinstance(actual[field], str) and isinstance(option, str)
                              and normalize(actual[field]) == normalize(option)
                              for option in options)
                expected_display = options
            elif field == "lead_investors":
                matches = {normalize(lead) for lead in actual[field]} == {normalize(lead) for lead in gold[field]}
                expected_display = gold[field]
            elif field == "hq_country":
                matches = (actual[field] is None and gold[field] is None
                           or isinstance(actual[field], str) and isinstance(gold[field], str)
                           and normalize(actual[field]) == normalize(gold[field]))
                expected_display = gold[field]
            else:
                matches = actual[field] == gold[field]
                expected_display = gold[field]
            if matches:
                points += weight
            else:
                errors.append(f"{gold['name']}.{field}: expected {expected_display!r}; got {actual[field]!r}")
    denominator = len(expected.keys() | predicted.keys()) * 13
    return {"score": points / denominator, "schema_valid": True,
            "exact": not errors, "errors": errors}
