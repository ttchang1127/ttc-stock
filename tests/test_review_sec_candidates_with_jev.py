import importlib.util
import pathlib
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "review_sec_candidates_with_jev",
    ROOT / "scripts/review_sec_candidates_with_jev.py",
)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def candidate():
    return {
        "id": "candidate-1",
        "ticker": "ARM",
        "type": "risk",
        "rule_key": "dilution_filing",
        "headline": "New offering filing",
        "evidence": ["Potential equity issuance"],
        "why_candidate": "Possible dilution",
        "filing_date": "2026-09-21",
        "materiality": {"planned_shares": 1000},
        "sources": [{"label": "SEC S-3", "url": "https://www.sec.gov/example"}],
    }


def jev_response():
    return {
        "model": "jev-1.13.0",
        "answers": {
            "direction": {
                "type": "choice", "choice": "risk", "confidence": 0.91,
                "probabilities": {"risk": 0.91, "improvement": 0.01,
                                  "conclusion": 0.07, "no_material_change": 0.01},
            },
            "materiality": {
                "type": "score", "score": 2.3, "confidence": 0.88,
                "probabilities": {"0": 0.01, "1": 0.09, "2": 0.50, "3": 0.40},
            },
            "source_sufficiency": {
                "type": "choice", "choice": "needs_primary_source_review", "confidence": 0.93,
                "probabilities": {"sufficient_for_priority": 0.06,
                                  "needs_primary_source_review": 0.93, "insufficient": 0.01},
            },
            "long_term_relevance": {"type": "noul", "noul": 0.94},
        },
    }


class JevCandidateReviewTests(unittest.TestCase):
    def test_questions_are_atomic_and_typed(self):
        questions = MODULE.questions()
        self.assertEqual({row["type"] for row in questions.values()}, {"choice", "score", "noul"})
        self.assertIn("Do not give investment advice", MODULE.candidate_state(candidate())["task"])

    def test_high_materiality_routes_to_urgent_human_review(self):
        review = MODULE.normalize_review(candidate(), jev_response())
        self.assertEqual(review["jev_direction"], "risk")
        self.assertEqual(review["route"], "urgent_human_review")
        self.assertTrue(review["requires_human_review"])
        self.assertEqual(review["confidence_floor"], 0.88)

    def test_missing_key_skips_without_calling_network(self):
        calls = []
        payload = MODULE.build_payload(
            {"generated_at": "2026-09-21", "candidates": [candidate()]},
            None,
            caller=lambda *args: calls.append(args),
        )
        self.assertEqual(payload["status"], "skipped_missing_api_key")
        self.assertEqual(calls, [])

    def test_complete_batch_records_versioned_model(self):
        payload = MODULE.build_payload(
            {"generated_at": "2026-09-21", "candidates": [candidate()]},
            "secret-not-logged",
            caller=lambda *args: jev_response(),
        )
        self.assertEqual(payload["status"], "complete")
        self.assertEqual(payload["reviewed_count"], 1)
        self.assertEqual(payload["models_used"], ["jev-1.13.0"])
        self.assertNotIn("secret-not-logged", str(payload))


if __name__ == "__main__":
    unittest.main()
