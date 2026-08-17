from __future__ import annotations

import unittest

from parametric_rag_defense.contracts import ContractError
from parametric_rag_defense.corroboration_arbiter import (
    parse_corroboration_arbiter,
)


def valid_judgment() -> dict:
    return {
        "action": "escalate",
        "confidence": 0.6,
        "independent_evidence_assessment": "unresolved",
        "internal_knowledge_assessment": "uncertain",
        "cross_view_assessment": "unresolved",
        "pivotal_fact": "Whether the named event occurred on the stated date.",
        "rationale": "Neither independent source nor stable recall resolves the event.",
    }


class CorroborationArbiterTests(unittest.TestCase):
    def test_parse_accepts_exact_contract(self) -> None:
        self.assertEqual(
            parse_corroboration_arbiter(valid_judgment())["action"], "escalate"
        )

    def test_parse_rejects_extra_fields(self) -> None:
        value = valid_judgment()
        value["condition"] = "clean"
        with self.assertRaises(ContractError):
            parse_corroboration_arbiter(value)


if __name__ == "__main__":
    unittest.main()
