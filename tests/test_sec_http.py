import email.message
import io
import os
import pathlib
import re
import sys
import unittest
import urllib.error
from unittest import mock

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import sec_http  # noqa: E402


class FakeResponse(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()


def http_error(code, retry_after=None):
    headers = email.message.Message()
    if retry_after is not None:
        headers["Retry-After"] = retry_after
    return urllib.error.HTTPError("https://www.sec.gov/x", code, "error", headers, None)


class SecHttpTests(unittest.TestCase):
    def setUp(self):
        self.requests, self.sleeps = [], []
        self.outcomes = []
        patches = [
            mock.patch.object(sec_http.urllib.request, "urlopen", side_effect=self.urlopen),
            mock.patch.object(sec_http.time, "sleep", side_effect=self.sleeps.append),
            mock.patch.object(sec_http, "_last_request", 0.0),
            mock.patch.dict(os.environ, {}, clear=False),
        ]
        for patcher in patches:
            patcher.start()
            self.addCleanup(patcher.stop)
        os.environ.pop("SEC_USER_AGENT", None)

    def urlopen(self, request, timeout):
        self.requests.append((request, timeout))
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return FakeResponse(outcome)

    def backoff_sleeps(self):
        return [delay for delay in self.sleeps if delay >= 1]

    def test_user_agent_defaults_to_a_real_contact_and_honours_the_variable(self):
        self.assertRegex(sec_http.user_agent(), r"\S+@\S+\.\w+")
        self.assertNotIn("example.com", sec_http.user_agent())
        os.environ["SEC_USER_AGENT"] = "Project contact@example.org"
        self.assertEqual(sec_http.user_agent(), "Project contact@example.org")
        os.environ["SEC_USER_AGENT"] = ""
        self.assertEqual(sec_http.user_agent(), sec_http.DEFAULT_USER_AGENT)

    def test_get_sends_agent_accept_range_and_timeout(self):
        self.outcomes = [b"0123456789"]
        body = sec_http.get("https://www.sec.gov/doc", accept="text/html", max_bytes=4, timeout=30)
        request, timeout = self.requests[0]
        self.assertEqual(body, b"0123")
        self.assertEqual(timeout, 30)
        self.assertEqual(request.get_header("User-agent"), sec_http.DEFAULT_USER_AGENT)
        self.assertEqual(request.get_header("Accept"), "text/html")
        self.assertEqual(request.get_header("Range"), "bytes=0-3")

    def test_get_json_and_text(self):
        self.outcomes = [b'{"filings": 1}', "café".encode() + b"\xff"]
        self.assertEqual(sec_http.get_json("https://data.sec.gov/a.json"), {"filings": 1})
        self.assertEqual(self.requests[0][0].get_header("Accept"), "application/json")
        self.assertEqual(sec_http.get_text("https://www.sec.gov/b"), "café")

    def test_transient_failures_are_retried_with_backoff(self):
        self.outcomes = [urllib.error.URLError("reset"), http_error(503), b"ok"]
        self.assertEqual(sec_http.get("https://www.sec.gov/c"), b"ok")
        self.assertEqual(len(self.requests), 3)
        self.assertEqual(self.backoff_sleeps(), [1.5, 3.0])

    def test_truncated_json_is_retried(self):
        self.outcomes = [b'{"filings": ', b'{"filings": []}']
        self.assertEqual(sec_http.get_json("https://data.sec.gov/d.json"), {"filings": []})
        self.assertEqual(len(self.requests), 2)

    def test_rate_limit_honours_retry_after_with_a_cap(self):
        self.outcomes = [http_error(429, "7"), http_error(429, "3600"), b"ok"]
        self.assertEqual(sec_http.get("https://www.sec.gov/e"), b"ok")
        self.assertEqual(self.backoff_sleeps(), [7.0, sec_http.MAX_RETRY_AFTER])

    def test_permanent_errors_fail_immediately(self):
        for code in (403, 404):
            self.outcomes, self.requests = [http_error(code)], []
            with self.assertRaises(urllib.error.HTTPError) as caught:
                sec_http.get("https://www.sec.gov/missing")
            self.assertEqual(caught.exception.code, code)
            self.assertEqual(len(self.requests), 1)

    def test_last_error_is_raised_after_the_final_attempt(self):
        self.outcomes = [TimeoutError("slow")] * 2
        with self.assertRaises(TimeoutError):
            sec_http.get("https://www.sec.gov/f", attempts=2)
        self.assertEqual(len(self.requests), 2)

    def test_requests_are_paced_under_ten_per_second(self):
        clock = iter([100.0, 100.0, 100.02, 100.11, 100.5, 100.5])
        with mock.patch.object(sec_http.time, "monotonic", side_effect=lambda: next(clock)):
            self.outcomes = [b"a", b"b", b"c"]
            for _ in range(3):
                sec_http.get("https://www.sec.gov/g")
        # 1st request: no wait.  2nd starts 0.02 s later: waits 0.09 s.  3rd: no wait.
        self.assertEqual([round(delay, 2) for delay in self.sleeps], [0.09])


class AdoptionTests(unittest.TestCase):
    SEC_SCRIPTS = (
        "analyze_exhibit_991", "check_new_annual_filings", "diff_periodic_filings",
        "fetch_quarterly_financials", "fetch_xbrl_financials", "ingest_periodic_filings",
        "sec_13f_stock_radar", "sec_advanced_radars", "sec_specialized_radars", "watch_sec_filings",
    )

    def test_scheduled_sec_clients_use_the_shared_module(self):
        for name in self.SEC_SCRIPTS:
            text = (ROOT / f"scripts/{name}.py").read_text()
            with self.subTest(script=name):
                self.assertIn("import sec_http", text)
                self.assertNotIn("urlopen(", text)
                self.assertIsNone(re.search(r"SEC_USER_AGENT|User-Agent", text))


if __name__ == "__main__":
    unittest.main()
