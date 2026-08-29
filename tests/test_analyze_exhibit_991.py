import importlib.util
import pathlib
import tempfile
import unittest
from unittest import mock

SCRIPT = pathlib.Path(__file__).resolve().parents[1] / "scripts" / "analyze_exhibit_991.py"
SPEC = importlib.util.spec_from_file_location("analyze_exhibit_991", SCRIPT)
analyze = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(analyze)


def event(items=None):
    return {
        "ticker": "TEST", "form": "8-K", "filing_date": "2026-08-20",
        "report_date": "2026-06-30", "accession": "0000000001-26-000123",
        "items": items if items is not None else ["2.02", "9.01"],
        "index_url": "https://www.sec.gov/Archives/edgar/data/1/000000000126000123/filing-index.html",
    }


INDEX_HTML = b'''<html><table summary="Document Format Files">
<tr><td>1</td><td>8-K</td><td><a href="main.htm">main.htm</a></td><td>8-K</td></tr>
<tr><td>2</td><td>Earnings Release</td><td><a href="earnings.htm">earnings.htm</a></td><td>EX-99.1</td></tr>
</table></html>'''

EXHIBIT_HTML = b'''<html><body>
<h1>Quarterly Results</h1>
<ul><li>Revenue was $120 million, an increase of 20% year over year.</li>
<li>GAAP gross margin was 42.5%.</li>
<li>Diluted earnings per share was $1.20.</li></ul>
<p>Cloud segment revenue was $70 million.</p>
<p>For the next quarter, the Company expects revenue between $125 million and $130 million.</p>
<p>Jane Doe, Chief Executive Officer, said demand remained strong.</p>
<p>Supply constraints remain a risk to the outlook.</p>
</body></html>'''


class Exhibit991Tests(unittest.TestCase):
    def test_only_item_202_8k_is_eligible(self):
        payload = {"events": [event(), event(["9.01"]), {**event(), "form": "6-K", "accession": "x"}]}
        with tempfile.TemporaryDirectory() as directory:
            path = pathlib.Path(directory) / "events.json"
            path.write_text(__import__("json").dumps(payload))
            rows = analyze.eligible_events(path)
        self.assertEqual([row["accession"] for row in rows], ["0000000001-26-000123"])

    def test_index_requires_exact_official_exhibit_991(self):
        found = analyze.official_exhibit_991(INDEX_HTML.decode(), event()["index_url"])
        self.assertEqual(found["type"], "EX-99.1")
        self.assertEqual(
            found["url"],
            "https://www.sec.gov/Archives/edgar/data/1/000000000126000123/earnings.htm",
        )
        malicious = INDEX_HTML.decode().replace('href="earnings.htm"', 'href="https://evil.example/earnings.htm"')
        self.assertIsNone(analyze.official_exhibit_991(malicious, event()["index_url"]))

    def test_all_seven_categories_keep_verbatim_evidence(self):
        blocks = analyze.evidence_blocks(EXHIBIT_HTML.decode())
        result = {
            key: analyze.extract_category_evidence(blocks, config)
            for key, config in analyze.CATEGORIES.items()
        }
        self.assertTrue(all(result.values()), result)
        self.assertIn("$120 million", result["revenue"][0]["excerpt"])
        self.assertIn("42.5%", result["gross_margin"][0]["excerpt"])

    def test_missing_category_stays_empty(self):
        blocks = analyze.evidence_blocks("<p>Revenue was $10 million.</p>")
        self.assertEqual(analyze.extract_category_evidence(blocks, analyze.CATEGORIES["eps"]), [])

    def test_guidance_accepts_expected_wording_and_prefers_numeric_row(self):
        blocks = analyze.evidence_blocks(
            "<p>Business Outlook – First Quarter Fiscal 2027</p>"
            "<table><tr><td>Revenue is expected to be between $2.2 billion "
            "and $2.4 billion.</td></tr></table>"
        )
        rows = analyze.extract_category_evidence(blocks, analyze.CATEGORIES["guidance"])
        self.assertIn("$2.2 billion", rows[0]["excerpt"])

    def test_analysis_card_is_accession_traceable(self):
        responses = [INDEX_HTML, EXHIBIT_HTML]
        with tempfile.TemporaryDirectory() as directory, mock.patch.object(
            analyze, "download", side_effect=responses
        ):
            root = pathlib.Path(directory)
            row = analyze.analyze_event(event(), "Test Company", root)
            card = (root / row["card"]).read_text()
        self.assertEqual(row["status"], "analyzed")
        self.assertEqual(row["coverage"], {"found": 7, "total": 7})
        self.assertIn("0000000001-26-000123", card)
        self.assertIn("官方來源", card)
        self.assertIn("保留缺值", card)

    def test_ambiguous_exhibit_fails_closed(self):
        duplicate = INDEX_HTML.replace(
            b"</table>",
            b'<tr><td>3</td><td>Other</td><td><a href="other.htm">other.htm</a></td><td>EX-99.1</td></tr></table>',
        )
        with tempfile.TemporaryDirectory() as directory, mock.patch.object(
            analyze, "download", return_value=duplicate
        ):
            row = analyze.analyze_event(event(), "Test Company", pathlib.Path(directory))
        self.assertEqual(row["status"], "review_required")
        self.assertIn("唯一", row["errors"][0])

    def test_failed_reanalysis_removes_stale_card(self):
        with tempfile.TemporaryDirectory() as directory, mock.patch.object(
            analyze, "download", return_value=b"<html>no exhibit</html>"
        ):
            root = pathlib.Path(directory)
            stale = analyze.card_path(root, event())
            stale.parent.mkdir(parents=True)
            stale.write_text("STALE")
            row = analyze.analyze_event(event(), "Test Company", root)
        self.assertEqual(row["status"], "review_required")
        self.assertFalse(stale.exists())
        self.assertEqual(row["removed_stale_cards"], [row["expected_card"]])


if __name__ == "__main__":
    unittest.main()
