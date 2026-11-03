"""Guard the market workflow's source-to-derived-data order.

SEC candidates read segment_thesis_linkage.json. Building that source after
candidates makes C-29 fail and prevents every market file from being published.
"""

import unittest
from pathlib import Path


WORKFLOW = Path(__file__).resolve().parents[1] / ".github/workflows/update-prices.yml"


class MarketWorkflowDependencyOrderTests(unittest.TestCase):
    def test_candidate_inputs_are_final_before_candidate_generation(self):
        workflow = WORKFLOW.read_text(encoding="utf-8")
        commands = (
            "python3 scripts/build_segment_thesis_linkage.py",
            "python3 scripts/generate_sec_daily_change_candidates.py",
            "python3 scripts/review_sec_candidates_with_jev.py",
            "python3 scripts/build_sec_position_impact_history.py",
            "python3 scripts/check_integrity.py",
        )
        positions = []
        for command in commands:
            self.assertEqual(workflow.count(command), 1, command)
            positions.append(workflow.index(command))
        self.assertEqual(positions, sorted(positions))


if __name__ == "__main__":
    unittest.main()
