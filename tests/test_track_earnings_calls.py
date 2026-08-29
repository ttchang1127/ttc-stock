import importlib.util
import pathlib
import tempfile
import unittest
from unittest import mock


SCRIPT = pathlib.Path(__file__).resolve().parents[1] / "scripts" / "track_earnings_calls.py"
SPEC = importlib.util.spec_from_file_location("track_earnings_calls", SCRIPT)
tracker = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(tracker)


def transcript_html():
    paragraphs = [
        "Example Inc. 2026 Q2 Management Discussion with prepared comments for the official quarterly earnings call.",
        "Customer demand and adoption remained strong while our backlog grew during the quarter.",
        "Gross margin reflected higher costs and depreciation expense from infrastructure investments.",
        "We increased capital expenditures and data center capacity to address supply constraints.",
        "For the next quarter, we expect revenue growth under the outlook provided today.",
        "We are confident in the pipeline although visibility remains limited in several markets.",
        "Tariff pressure and supply constraints remain important risks and potential headwinds.",
        "Revenue performance included several products and geographic markets discussed by management.",
        "Operating expenses include research investment and additional infrastructure depreciation.",
        "The company continues to invest while monitoring costs and available manufacturing capacity.",
        "Question and Answer Session",
        "Can you help us understand what is driving demand and how should investors think about capacity?",
        "Management responded that supply planning depends on customer schedules and market conditions.",
    ]
    return ("<html><body>" + "".join(f"<p>{text}</p>" for text in paragraphs) + "</body></html>").encode()


class EarningsCallTrackerTests(unittest.TestCase):
    def test_url_allowlist_requires_exact_https_host(self):
        self.assertTrue(tracker.allowed_url("https://ir.example.com/call.pdf", ["ir.example.com"]))
        self.assertFalse(tracker.allowed_url("http://ir.example.com/call.pdf", ["ir.example.com"]))
        self.assertFalse(tracker.allowed_url("https://ir.example.com.evil.test/call.pdf", ["ir.example.com"]))

    def test_browser_impersonation_strategy_is_explicit_and_keeps_referer(self):
        config = {
            "landing_url": "https://ir.example.com/results",
            "fetch_strategy": "browser_impersonation",
        }
        with mock.patch.object(
            tracker, "download_browser_impersonated", return_value=(b"payload", "application/pdf")
        ) as browser_download:
            result = tracker.download_for_config("https://ir.example.com/call.pdf", config, timeout=10)
        self.assertEqual(result, (b"payload", "application/pdf"))
        browser_download.assert_called_once_with(
            "https://ir.example.com/call.pdf", 45, "https://ir.example.com/results"
        )

    def test_browser_impersonation_failure_is_normalized_for_fail_closed_path(self):
        fake_requests = mock.Mock()
        fake_requests.get.side_effect = RuntimeError("blocked")
        with mock.patch.object(tracker, "curl_requests", fake_requests):
            with self.assertRaises(tracker.urllib.error.URLError):
                tracker.download_browser_impersonated("https://ir.example.com/call.pdf")

    def test_cross_domain_material_requires_official_link_or_recent_attestation(self):
        config = {
            "landing_url": "https://ir.example.com/event", "material_url": "https://cdn.example.net/call.pdf",
        }
        with mock.patch.object(tracker, "download", return_value=(b"<a href='elsewhere'>Other</a>", "text/html")):
            provenance, errors = tracker.verify_provenance(config)
        self.assertEqual(provenance, {})
        self.assertTrue(errors)

        config.update(
            provenance_verified_on=tracker.now_utc()[:10],
            provenance_note="Official IR page was manually checked.",
        )
        with mock.patch.object(tracker, "download", side_effect=tracker.urllib.error.URLError("blocked")):
            provenance, errors = tracker.verify_provenance(config)
        self.assertEqual(provenance["status"], "manual_official_page_attestation")
        self.assertEqual(errors, [])

    def test_cross_domain_protocol_relative_official_link_is_verified(self):
        config = {
            "landing_url": "https://ir.example.com/event",
            "material_url": "https://cdn.example.net/call.pdf",
        }
        page = b"<a href='//cdn.example.net/call.pdf'>Official transcript</a>"
        with mock.patch.object(tracker, "download", return_value=(page, "text/html")):
            provenance, errors = tracker.verify_provenance(config)
        self.assertEqual(provenance["status"], "official_page_link")
        self.assertEqual(errors, [])

    def test_discovery_only_surfaces_explicitly_newer_official_text(self):
        config = {
            "period": "2026 Q2", "landing_url": "https://ir.example.com/results",
            "material_url": "https://ir.example.com/q2.pdf", "allowed_hosts": ["ir.example.com"],
        }
        page = b"""<html><body>
          <a href='/2026-q1-transcript.pdf'>2026 Q1 Earnings Call Transcript</a>
          <a href='/2026-q3-transcript.pdf'>2026 Q3 Earnings Call Transcript</a>
          <a href='https://evil.example.net/2026-q4-transcript.pdf'>2026 Q4 Transcript</a>
        </body></html>"""
        with mock.patch.object(tracker, "download", return_value=(page, "text/html")):
            result = tracker.discover_newer_material(config)
        self.assertEqual(result["status"], "checked")
        self.assertEqual([item["period_key"] for item in result["newer_candidates"]], ["2026 Q3"])
        self.assertEqual(result["newer_candidates"][0]["url"], "https://ir.example.com/2026-q3-transcript.pdf")

    def test_full_transcript_preserves_short_evidence_and_q_and_a(self):
        config = {
            "company_name": "Example Inc.", "period": "2026 Q2", "call_date": "2026-07-01",
            "landing_url": "https://ir.example.com/", "material_url": "https://ir.example.com/call.html",
            "source_type": "full_transcript", "allowed_hosts": ["ir.example.com"],
            "identity_patterns": [r"\bExample Inc\b", r"\b2026 Q2\b"],
        }
        with tempfile.TemporaryDirectory() as directory, mock.patch.object(
            tracker, "download", return_value=(transcript_html(), "text/html")
        ):
            root = pathlib.Path(directory)
            row = tracker.analyze_company("TEST", config, {"filings": []}, root)
            self.assertEqual(row["status"], "analyzed")
            self.assertTrue(row["q_and_a_available"])
            self.assertEqual(set(row["categories"]), set(tracker.CATEGORIES))
            self.assertTrue(row["categories"]["analyst_questions"])
            self.assertTrue(all(
                item["section"] == "prepared"
                for key, evidence in row["categories"].items() if key != "analyst_questions"
                for item in evidence
            ))
            self.assertTrue(all(
                len(item["excerpt"].rstrip("…").split()) <= tracker.MAX_EXCERPT_WORDS
                for evidence in row["categories"].values() for item in evidence
            ))
            self.assertTrue((root / row["card"]).is_file())

    def test_q_and_a_transition_accepts_official_take_your_questions_wording(self):
        html = b"""<html><body>
          <p>Example Inc. 2026 Q2 management remarks and quarterly results.</p>
          <p>We expect revenue growth and continued customer demand next quarter.</p>
          <p>Sundar, Philipp and I will now take your questions.</p>
          <p>Our first question comes from Brian Nowak with Morgan Stanley.</p>
          <p>Can you help us understand forward capital expenditures and capacity?</p>
        </body></html>"""
        blocks = tracker.source_blocks(html, "text/html", "https://ir.example.com/call.html")
        self.assertEqual([block["section"] for block in blocks[:2]], ["prepared", "prepared"])
        self.assertTrue(all(block["section"] == "q_and_a" for block in blocks[2:]))

    def test_prepared_remarks_never_claims_analyst_questions(self):
        config = {
            "company_name": "Example Inc.", "period": "2026 Q2", "call_date": "2026-07-01",
            "landing_url": "https://ir.example.com/", "material_url": "https://ir.example.com/remarks.html",
            "source_type": "prepared_remarks", "allowed_hosts": ["ir.example.com"],
            "identity_patterns": [r"\bExample Inc\b", r"\b2026 Q2\b"],
        }
        with tempfile.TemporaryDirectory() as directory, mock.patch.object(
            tracker, "download", return_value=(transcript_html(), "text/html")
        ):
            row = tracker.analyze_company("TEST", config, {"filings": []}, pathlib.Path(directory))
            self.assertEqual(row["status"], "analyzed")
            self.assertFalse(row["q_and_a_available"])
            self.assertEqual(row["categories"]["analyst_questions"], [])

    def test_replay_only_removes_stale_text_card(self):
        config = {
            "company_name": "Example Inc.", "period": "2026 Q2", "call_date": "2026-07-01",
            "landing_url": "https://ir.example.com/", "material_url": "https://ir.example.com/replay",
            "source_type": "webcast_replay", "allowed_hosts": ["ir.example.com"],
        }
        with tempfile.TemporaryDirectory() as directory, mock.patch.object(
            tracker, "probe_url", return_value={"status": "reachable", "http_status": 200}
        ):
            root = pathlib.Path(directory)
            stale = tracker.card_path(root, "TEST", config["period"])
            stale.parent.mkdir(parents=True)
            stale.write_text("stale")
            row = tracker.analyze_company("TEST", config, {"filings": []}, root)
            self.assertEqual(row["status"], "replay_only")
            self.assertEqual(row["link_check"]["status"], "reachable")
            self.assertFalse(stale.exists())

    def test_semantic_filters_reject_boilerplate_and_wrong_context(self):
        blocks = [
            {"section": "prepared", "text": "A minimum revenue guarantee gives lenders the confidence to finance the facility."},
            {"section": "prepared", "text": "These forward-looking statements are subject to risks and uncertainties and actual results may differ materially."},
            {"section": "prepared", "text": "We introduced controller products supporting Data Center, Enterprise and Telco applications."},
            {"section": "prepared", "text": "Tariff pressure and supply constraints remain important operational headwinds this quarter."},
        ]
        self.assertEqual(tracker.extract_evidence(blocks, tracker.CATEGORIES["confidence"]), [])
        self.assertEqual(tracker.extract_evidence(blocks[:3], tracker.CATEGORIES["capital_supply"]), [])
        risk = tracker.extract_evidence(blocks, tracker.CATEGORIES["risks"])
        self.assertEqual(len(risk), 1)
        self.assertIn("Tariff pressure", risk[0]["excerpt"])

    def test_customer_booking_and_generic_question_are_not_investment_evidence(self):
        prepared = [{
            "section": "prepared",
            "text": "The customer completed a vehicle booking flow from selection through payment in one conversation.",
        }]
        questions = [{
            "section": "q_and_a",
            "text": "Could you help us understand some of the differences here?",
        }]
        self.assertEqual(tracker.extract_evidence(prepared, tracker.CATEGORIES["demand_growth"]), [])
        self.assertEqual(tracker.extract_evidence(questions, tracker.CATEGORIES["analyst_questions"]), [])
        product_usage = [{
            "section": "prepared",
            "text": "Average weekly engagement is now on par with Outlook and Teams across active users.",
        }]
        self.assertEqual(tracker.extract_evidence(product_usage, tracker.CATEGORIES["guidance"]), [])
        generic_outlook_transition = [{
            "section": "prepared",
            "text": "I'll end with some commentary on our outlook for the third quarter and full year 2026.",
        }]
        self.assertEqual(tracker.extract_evidence(generic_outlook_transition, tracker.CATEGORIES["guidance"]), [])
        annual_report_boilerplate = [{
            "section": "prepared",
            "text": "Important risk factors that may affect our business are described in our Annual Report on Form 20-F filed with the SEC.",
        }]
        self.assertEqual(tracker.extract_evidence(annual_report_boilerplate, tracker.CATEGORIES["risks"]), [])

    def test_fingerprint_detects_evidence_change_but_ignores_last_verified_time(self):
        base = {
            "period": "2026 Q2", "call_date": "2026-07-01", "material_url": "https://ir.example.com/call",
            "source_type": "full_transcript", "source_sha256": "a" * 64, "status": "analyzed",
            "freshness": {"status": "current"}, "categories": {"guidance": []},
            "last_verified_at": "2026-07-01T00:00:00+00:00",
        }
        later = {**base, "last_verified_at": "2026-07-02T00:00:00+00:00"}
        changed = {**later, "categories": {"guidance": [{"excerpt": "Revenue guidance increased."}]}}
        discovered = {**later, "discovery": {"status": "checked", "newer_candidates": [{"period_key": "2026 Q3"}]}}
        version = tracker.PARSER_VERSION
        self.assertEqual(tracker.row_fingerprint(version, base), tracker.row_fingerprint(version, later))
        self.assertNotEqual(tracker.row_fingerprint(version, base), tracker.row_fingerprint(version, changed))
        self.assertNotEqual(tracker.row_fingerprint(version, base), tracker.row_fingerprint(version, discovered))

    def test_wrong_company_or_period_is_rejected(self):
        config = {
            "company_name": "Example Inc.", "period": "2026 Q2", "call_date": "2026-07-01",
            "landing_url": "https://ir.example.com/", "material_url": "https://ir.example.com/call.html",
            "source_type": "full_transcript", "allowed_hosts": ["ir.example.com"],
            "identity_patterns": [r"\bDifferent Company\b", r"\b2026 Q2\b"],
        }
        with tempfile.TemporaryDirectory() as directory, mock.patch.object(
            tracker, "download", return_value=(transcript_html(), "text/html")
        ):
            row = tracker.analyze_company("TEST", config, {"filings": []}, pathlib.Path(directory))
            self.assertEqual(row["status"], "review_required")
            self.assertIn("Different Company", row["errors"][0])

    def test_full_transcript_without_q_and_a_is_rejected(self):
        html = transcript_html().replace(b"Question and Answer Session", b"Additional Management Discussion")
        config = {
            "company_name": "Example Inc.", "period": "2026 Q2", "call_date": "2026-07-01",
            "landing_url": "https://ir.example.com/", "material_url": "https://ir.example.com/call.html",
            "source_type": "full_transcript", "allowed_hosts": ["ir.example.com"],
            "identity_patterns": [r"\bExample Inc\b", r"\b2026 Q2\b"],
        }
        with tempfile.TemporaryDirectory() as directory, mock.patch.object(
            tracker, "download", return_value=(html, "text/html")
        ):
            row = tracker.analyze_company("TEST", config, {"filings": []}, pathlib.Path(directory))
            self.assertEqual(row["status"], "review_required")
            self.assertIn("Q&A", row["errors"][0])

    def test_transient_download_failure_keeps_last_verified_card(self):
        config = {
            "company_name": "Example Inc.", "period": "2026 Q2", "call_date": "2026-07-01",
            "landing_url": "https://ir.example.com/", "material_url": "https://ir.example.com/call.html",
            "source_type": "full_transcript", "allowed_hosts": ["ir.example.com"],
            "identity_patterns": [r"\bExample Inc\b", r"\b2026 Q2\b"],
        }
        with tempfile.TemporaryDirectory() as directory:
            root = pathlib.Path(directory)
            card = tracker.card_path(root, "TEST", config["period"])
            card.parent.mkdir(parents=True)
            card.write_text("last verified")
            previous = {
                **config, "ticker": "TEST", "status": "analyzed", "card": str(card.relative_to(root)),
                "categories": {key: [] for key in tracker.CATEGORIES},
                "coverage": {"found": 0, "total": len(tracker.CATEGORIES)},
                "q_and_a_available": True, "source_sha256": "a" * 64,
                "exhibit_comparison": {"status": "unavailable"}, "last_verified_at": "2026-07-02T00:00:00+00:00",
            }
            with mock.patch.object(tracker, "download", side_effect=tracker.urllib.error.URLError("temporary")):
                row = tracker.analyze_company("TEST", config, {"filings": []}, root, previous)
            self.assertEqual(row["status"], "analyzed_cached")
            self.assertTrue(card.exists())
            self.assertEqual(row["last_verified_at"], previous["last_verified_at"])

    def test_freshness_flags_source_after_newer_financial_filing(self):
        config = {"call_date": "2026-01-01"}
        company = {"periods": [{"period_end": "2026-06-30", "filing_date": "2026-07-31"}]}
        result = tracker.source_freshness(config, company)
        self.assertEqual(result["status"], "stale")
        self.assertGreater(result["lag_days"], 45)


if __name__ == "__main__":
    unittest.main()
