"""
tests/test_prompts.py
~~~~~~~~~~~~~~~~~~~~~
Tests for finamt.agents.prompts — category list and 4 prompt builders.
"""

from __future__ import annotations

from finamt.agents.prompts import (
    RECEIPT_CATEGORIES,
    build_agent1_prompt,
    build_agent2_prompt,
    build_agent3_prompt,
    build_agent4_prompt,
)


class TestReceiptCategories:
    def test_is_list_of_strings(self):
        assert isinstance(RECEIPT_CATEGORIES, list)
        assert all(isinstance(c, str) for c in RECEIPT_CATEGORIES)

    def test_contains_expected_categories(self):
        expected = {
            "services",
            "products",
            "material",
            "equipment",
            "software",
            "licensing",
            "telecommunication",
            "travel",
            "car",
            "education",
            "utilities",
            "insurance",
            "financial",
            "office",
            "marketing",
            "donations",
            "public_fees",
            "tax_settlement",
            "capital_movement",
            "other",
        }
        assert expected == set(RECEIPT_CATEGORIES)

    def test_no_duplicates(self):
        assert len(RECEIPT_CATEGORIES) == len(set(RECEIPT_CATEGORIES))

    def test_other_is_present(self):
        assert "other" in RECEIPT_CATEGORIES


class TestSandwichPattern:
    """All prompts must start with an instruction and end with 'Return only JSON:'"""

    def test_agent1_starts_with_instruction(self):
        p = build_agent1_prompt("text")
        assert p.startswith("Extract receipt")

    def test_agent1_ends_with_reminder(self):
        assert build_agent1_prompt("text").strip().endswith("Return only JSON:")

    def test_agent2_ends_with_reminder(self):
        assert build_agent2_prompt("text", "purchase").strip().endswith("Return only JSON:")

    def test_agent3_ends_with_reminder(self):
        assert build_agent3_prompt("text").strip().endswith("Return only JSON:")

    def test_agent4_ends_with_reminder(self):
        assert build_agent4_prompt("text").strip().endswith("Return only JSON:")


class TestAgent1Prompt:
    def test_receipt_text_injected(self):
        text = "UNIQUE_RECEIPT_CONTENT_XYZ"
        assert text in build_agent1_prompt(text)

    def test_all_categories_present(self):
        p = build_agent1_prompt("text")
        for cat in RECEIPT_CATEGORIES:
            assert cat in p

    def test_required_json_keys_present(self):
        p = build_agent1_prompt("text")
        for key in ("receipt_number", "receipt_date", "category"):
            assert key in p

    def test_empty_text_does_not_raise(self):
        assert isinstance(build_agent1_prompt(""), str)

    def test_text_truncated_at_3000_chars(self):
        long_text = "x" * 5000
        p = build_agent1_prompt(long_text)
        assert "truncated" in p


class TestAgent2Prompt:
    def test_purchase_mentions_vendor(self):
        assert "vendor" in build_agent2_prompt("text", "purchase")

    def test_sale_mentions_client(self):
        assert "client" in build_agent2_prompt("text", "sale")

    def test_required_json_keys_present(self):
        p = build_agent2_prompt("text", "purchase")
        for key in (
            "name",
            "vat_id",
            "tax_number",
            "street_and_number",
            "postcode",
            "city",
            "state",
            "country",
        ):
            assert key in p

    def test_receipt_text_injected(self):
        text = "VENDOR_NAME_ABC"
        assert text in build_agent2_prompt(text, "purchase")


class TestAgent3Prompt:
    def test_required_json_keys_present(self):
        p = build_agent3_prompt("text")
        for key in ("total_amount", "vat_percentage", "vat_amount"):
            assert key in p

    def test_receipt_text_injected(self):
        text = "AMOUNT_12345"
        assert text in build_agent3_prompt(text)

    def test_german_format_hint_present(self):
        assert "1.234,56" in build_agent3_prompt("text")


class TestAgent4Prompt:
    def test_items_key_present(self):
        assert "items" in build_agent4_prompt("text")

    def test_required_item_keys_present(self):
        p = build_agent4_prompt("text")
        for key in ("description", "vat_rate", "vat_amount", "total_price"):
            assert key in p

    def test_empty_items_instruction_present(self):
        assert "[]" in build_agent4_prompt("text")

    def test_receipt_text_injected(self):
        text = "ITEM_DESCRIPTION_XYZ"
        assert text in build_agent4_prompt(text)
