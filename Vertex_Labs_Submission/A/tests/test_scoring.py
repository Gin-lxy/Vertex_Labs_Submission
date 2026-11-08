from pathlib import Path
import sys

import pytest


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


ARTICLE = (
    "Aurora Robotics raised $20 million in Series A. "
    "Northstar Ventures led the round."
)
EXPECTED = [
    {
        "name": "Aurora Robotics",
        "hq_country": "Canada",
        "sector": "Technology",
        "round": "Series A",
        "amount_usd": 20000000,
        "lead_investors": ["Northstar Ventures"],
        "evidence_terms": [
            ["Aurora Robotics"],
            ["$20 million", "20 million"],
            ["Northstar Ventures led the round"],
        ],
    }
]
CASE = {"id": "aurora-001", "article": ARTICLE, "expected": EXPECTED}
VALID_RAW = (
    '[{"name":"Aurora Robotics","hq_country":"Canada",'
    '"sector":"Technology","round":"Series A",'
    '"amount_usd":20000000,"lead_investors":["Northstar Ventures"],'
    '"evidence":"Aurora Robotics raised $20 million in Series A. '
    'Northstar Ventures led the round."}]'
)


def evaluate(raw, case=CASE):
    import scoring

    stripped = raw.lstrip()
    if stripped.startswith("["):
        raw = '{"companies":' + stripped + "}"
    return scoring.evaluate_output(raw, case)


def assert_valid_result(result, score, exact):
    assert isinstance(result["score"], (int, float))
    assert not isinstance(result["score"], bool)
    assert 0 <= result["score"] <= 1
    assert result["score"] == pytest.approx(score)
    assert result["schema_valid"] is True
    assert result["exact"] is exact
    assert isinstance(result["errors"], list)
    assert all(isinstance(error, str) for error in result["errors"])


def assert_invalid_result(result):
    assert result["score"] == 0
    assert result["schema_valid"] is False
    assert result["exact"] is False
    assert isinstance(result["errors"], list)
    assert result["errors"]
    assert all(isinstance(error, str) for error in result["errors"])


def test_correct_result_scores_one_and_is_exact():
    assert_valid_result(evaluate(VALID_RAW), 1, True)


def test_company_and_lead_names_ignore_case_and_whitespace():
    raw = (
        '[{"name":"  aurora   robotics ","hq_country":"Canada",'
        '"sector":"Technology","round":"Series A",'
        '"amount_usd":20000000,"lead_investors":[" northstar   VENTURES "],'
        '"evidence":"Aurora Robotics raised $20 million in Series A. '
        'Northstar Ventures led the round."}]'
    )
    assert_valid_result(evaluate(raw), 1, True)


def test_sector_alias_matches_the_gold_sector():
    case = {
        "id": "aurora-alias",
        "article": ARTICLE,
        "expected": [
            {
                **EXPECTED[0],
                "sector_aliases": ["AI", "Software"],
            }
        ],
    }
    raw = VALID_RAW.replace('"sector":"Technology"', '"sector":"AI"')
    assert_valid_result(evaluate(raw, case), 1, True)


def test_company_order_does_not_change_score_or_exactness():
    article = (
        "Aurora Robotics raised $20 million in Series A led by Northstar Ventures. "
        "Beacon Systems raised $8 million in Seed led by Cedar Capital."
    )
    case = {
        "id": "two-companies",
        "article": article,
        "expected": [
            {
                "name": "Aurora Robotics",
                "hq_country": "Canada",
                "sector": "Technology",
                "round": "Series A",
                "amount_usd": 20000000,
                "lead_investors": ["Northstar Ventures"],
                "evidence_terms": [["Aurora Robotics"], ["$20 million"], ["Northstar Ventures"]],
            },
            {
                "name": "Beacon Systems",
                "hq_country": "United States",
                "sector": "Technology",
                "round": "Seed",
                "amount_usd": 8000000,
                "lead_investors": ["Cedar Capital"],
                "evidence_terms": [["Beacon Systems"], ["$8 million"], ["Cedar Capital"]],
            },
        ],
    }
    raw = (
        '[{"name":"Beacon Systems","hq_country":"United States",'
        '"sector":"Technology","round":"Seed","amount_usd":8000000,'
        '"lead_investors":["Cedar Capital"],"evidence":"Beacon Systems raised $8 million in Seed led by Cedar Capital."},'
        '{"name":"Aurora Robotics","hq_country":"Canada",'
        '"sector":"Technology","round":"Series A","amount_usd":20000000,'
        '"lead_investors":["Northstar Ventures"],"evidence":"Aurora Robotics raised $20 million in Series A led by Northstar Ventures."}]'
    )
    assert_valid_result(evaluate(raw, case), 1, True)


def test_different_valid_article_quote_can_be_exact():
    article = (
        "Aurora Robotics raised $20 million in Series A. "
        "Northstar Ventures led the round."
    )
    case = {
        "id": "alternate-evidence",
        "article": article,
        "expected": [
            {
                **EXPECTED[0],
                "evidence_terms": [
                    ["raised $20 million in Series A", "secured $20 million"],
                    ["Northstar Ventures led the round", "Northstar led"],
                ],
            }
        ],
    }
    raw = VALID_RAW.replace(
        "Aurora Robotics raised $20 million in Series A. Northstar Ventures led the round.",
        "raised $20 million in Series A. Northstar Ventures led the round.",
    )
    assert_valid_result(evaluate(raw, case), 1, True)


def test_missing_company_receives_union_normalized_denominator_penalty():
    case = {
        "id": "missing-company",
        "article": ARTICLE + " Beacon Systems raised $8 million in Seed led by Cedar Capital.",
        "expected": [
            {**EXPECTED[0], "evidence_terms": [["Aurora Robotics"]]},
            {
                "name": "Beacon Systems",
                "hq_country": "United States",
                "sector": "Technology",
                "round": "Seed",
                "amount_usd": 8000000,
                "lead_investors": ["Cedar Capital"],
                "evidence_terms": [["Beacon Systems"]],
            },
        ],
    }
    result = evaluate(VALID_RAW, case)
    assert_valid_result(result, 0.5, False)


def test_extra_company_receives_union_normalized_denominator_penalty():
    raw = VALID_RAW[:-1] + (
        ',{"name":"Beacon Systems","hq_country":"United States",'
        '"sector":"Technology","round":"Seed","amount_usd":8000000,'
        '"lead_investors":["Cedar Capital"],"evidence":"Aurora Robotics raised $20 million in Series A."}]'
    )
    result = evaluate(raw)
    assert_valid_result(result, 0.5, False)


def test_valuation_in_amount_field_does_not_match_financing_amount():
    raw = VALID_RAW.replace('"amount_usd":20000000', '"amount_usd":500000000')
    result = evaluate(raw)
    assert_valid_result(result, 10 / 13, False)


def test_article_quote_without_gold_evidence_terms_loses_evidence_points():
    case = {
        "id": "unsupported-quote",
        "article": ARTICLE + " Aurora Robotics is headquartered in Canada.",
        "expected": [
            {
                **EXPECTED[0],
                "evidence_terms": [["raised $20 million in Series A"], ["Northstar Ventures led"]],
            }
        ],
    }
    raw = VALID_RAW.replace(
        "Aurora Robotics raised $20 million in Series A. Northstar Ventures led the round.",
        "Aurora Robotics is headquartered in Canada.",
    )
    result = evaluate(raw, case)
    assert_valid_result(result, 11 / 13, False)


def test_quote_not_contiguous_in_article_is_rejected():
    raw = VALID_RAW.replace(
        "Aurora Robotics raised $20 million in Series A. Northstar Ventures led the round.",
        "Aurora Robotics raised $20 million in Series A, led by Northstar Ventures.",
    )
    assert_invalid_result(evaluate(raw))


def test_empty_expected_and_empty_output_score_one():
    case = {"id": "no-financing", "article": "No financing was reported.", "expected": []}
    assert_valid_result(evaluate("[]", case), 1, True)


def test_empty_output_for_financing_case_scores_zero():
    assert_valid_result(evaluate("[]"), 0, False)


def test_top_level_array_is_rejected():
    import scoring

    assert_invalid_result(scoring.evaluate_output("[]", CASE))


def test_malformed_json_is_rejected():
    assert_invalid_result(evaluate('{"name":'))


def test_duplicate_json_keys_are_rejected():
    raw = (
        '[{"name":"Aurora Robotics","hq_country":"Canada",'
        '"sector":"Technology","round":"Series A",'
        '"amount_usd":20000000,"amount_usd":20000000,'
        '"lead_investors":["Northstar Ventures"],"evidence":"Aurora Robotics raised $20 million in Series A. Northstar Ventures led the round."}]'
    )
    assert_invalid_result(evaluate(raw))


def test_duplicate_company_names_after_normalization_are_rejected():
    raw = VALID_RAW[:-1] + (
        ',{"name":"  aurora   ROBOTICS ","hq_country":"Canada",'
        '"sector":"Technology","round":"Series A","amount_usd":20000000,'
        '"lead_investors":["Northstar Ventures"],"evidence":"Aurora Robotics raised $20 million in Series A."}]'
    )
    assert_invalid_result(evaluate(raw))


def test_additional_output_field_is_rejected():
    raw = VALID_RAW.replace(
        '"amount_usd":20000000',
        '"amount_usd":20000000,"valuation_usd":500000000',
    )
    assert_invalid_result(evaluate(raw))


def test_boolean_amount_is_rejected():
    raw = VALID_RAW.replace('"amount_usd":20000000', '"amount_usd":true')
    assert_invalid_result(evaluate(raw))


@pytest.mark.parametrize("bad_amount", ["NaN", "Infinity", "-Infinity"])
def test_nonfinite_amount_is_rejected(bad_amount):
    raw = VALID_RAW.replace('"amount_usd":20000000', f'"amount_usd":{bad_amount}')
    assert_invalid_result(evaluate(raw))


def test_negative_amount_is_rejected():
    raw = VALID_RAW.replace('"amount_usd":20000000', '"amount_usd":-1')
    assert_invalid_result(evaluate(raw))


def test_markdown_fence_is_rejected():
    assert_invalid_result(evaluate("```json\n" + VALID_RAW + "\n```"))


@pytest.mark.parametrize("bad_round", ["Quarterly", None])
def test_invalid_or_null_round_is_rejected(bad_round):
    value = "null" if bad_round is None else f'"{bad_round}"'
    raw = VALID_RAW.replace('"round":"Series A"', f'"round":{value}')
    assert_invalid_result(evaluate(raw))


@pytest.mark.parametrize(
    "old,new",
    [
        ('"hq_country":"Canada"', '"hq_country":[]'),
        ('"sector":"Technology"', '"sector":[]'),
        ('"amount_usd":20000000', '"amount_usd":"20000000"'),
        ('"lead_investors":["Northstar Ventures"]', '"lead_investors":null'),
        ('"evidence":"Aurora Robotics raised $20 million in Series A. Northstar Ventures led the round."', '"evidence":[]'),
    ],
)
def test_invalid_field_types_are_rejected(old, new):
    assert_invalid_result(evaluate(VALID_RAW.replace(old, new)))


def test_duplicate_lead_investors_after_normalization_are_rejected():
    raw = VALID_RAW.replace(
        '["Northstar Ventures"]',
        '["Northstar Ventures"," northstar   VENTURES "]',
    )
    assert_invalid_result(evaluate(raw))


def test_evidence_over_300_characters_is_rejected():
    long_evidence = "Aurora Robotics " + ("raised $20 million in Series A. " * 10)
    raw = VALID_RAW.replace(
        "Aurora Robotics raised $20 million in Series A. Northstar Ventures led the round.",
        long_evidence,
    )
    assert_invalid_result(evaluate(raw))


def test_large_json_integer_is_scored_without_float_overflow():
    raw = VALID_RAW.replace('"amount_usd":20000000', '"amount_usd":' + "9" * 400)
    assert_valid_result(evaluate(raw), 10 / 13, False)


def test_nonempty_prediction_for_negative_article_scores_zero():
    case = {"id": "historical-only", "article": ARTICLE, "expected": []}
    assert_valid_result(evaluate(VALID_RAW, case), 0, False)
