import contextlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import mail_cli
from policy import QUESTIONS, classify


class MailTests(unittest.TestCase):
    def test_dotenv_key_and_environment_priority(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / ".env"
            path.write_text('# demo\nTYPESAFE_API_KEY="demo-key"\n', encoding="utf-8")
            with patch.dict("os.environ", {}, clear=True):
                self.assertEqual(mail_cli.api_key(path), "demo-key")
            with patch.dict("os.environ", {"TYPESAFE_API_KEY": "environment-key"}):
                self.assertEqual(mail_cli.api_key(path), "environment-key")
            with patch.dict("os.environ", {"TYPESAFE_API_KEY": ""}):
                self.assertEqual(mail_cli.api_key(path), "")

    def test_policy_outcomes_and_boundaries(self):
        cases = [
            ([.9, .8, .9, .9], "緊急"),
            ([.9, .1, .8, .1], "高"),
            ([.9, .1, .1, .9], "高"),
            ([.7, .3, .3, .3], "通常"),
            ([.3, .1, .1, .1], "対応不要"),
            ([.5, .1, .1, .1], "判断保留"),
            ([.9, .5, .1, .1], "判断保留"),
            ([.1, .8, .1, .1], "判断保留"),
        ]
        for values, expected in cases:
            with self.subTest(values=values):
                self.assertEqual(classify(dict(zip(QUESTIONS, values)))[0], expected)

    def test_reject_invalid_or_missing_probability(self):
        for invalid in (True, None, "0.9", float("nan"), float("inf"), 1.1, -.1):
            answers = {k: {"type": "noul", "noul": .1} for k in QUESTIONS}
            answers["today"]["noul"] = invalid
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                mail_cli.probabilities({"answers": answers})
        with self.assertRaises(ValueError):
            mail_cli.probabilities({"answers": {}})

    def test_eml_html_and_attachment_exclusion(self):
        from email.message import EmailMessage
        message = EmailMessage()
        message["Subject"] = "予約変更"
        message["From"] = "private@example.com"
        message.set_content("<p>本日の予約</p><script>secret</script>", subtype="html")
        message.add_attachment(b"private attachment", maintype="application", subtype="octet-stream", filename="note.bin")
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "mail.eml"
            path.write_bytes(message.as_bytes())
            mails = mail_cli.load_emails(path)
        self.assertIn("本日の予約", mails[0]["body"])
        payload = json.dumps(mail_cli.payload_for(mails[0], "2026-11-08T09:00:00+09:00", "jev-latest"))
        for excluded in ("private@example.com", "private attachment", "secret"):
            self.assertNotIn(excluded, payload)

    def test_default_never_calls_api(self):
        output = io.StringIO()
        with patch.object(mail_cli, "call_api") as api, contextlib.redirect_stdout(output):
            code = mail_cli.main(["examples/emails.json", "--at", "2026-11-08T09:00:00+09:00"])
        self.assertEqual(code, 0)
        api.assert_not_called()
        self.assertEqual(len(output.getvalue().splitlines()), 5)

    def test_mocked_api_classification(self):
        answer = {"answers": {k: {"type": "noul", "noul": .1} for k in QUESTIONS}}
        output = io.StringIO()
        with patch.dict("os.environ", {"TYPESAFE_API_KEY": "test-placeholder"}), patch.object(mail_cli, "call_api", return_value=answer) as api, contextlib.redirect_stdout(output):
            code = mail_cli.main(["examples/emails.json", "--send"])
        self.assertEqual(code, 0)
        self.assertEqual(api.call_count, 5)
        self.assertTrue(all(json.loads(line)["label"] == "対応不要" for line in output.getvalue().splitlines()))

    def test_api_failure_not_classified(self):
        output, error = io.StringIO(), io.StringIO()
        with patch.dict("os.environ", {"TYPESAFE_API_KEY": "test-placeholder"}), patch.object(mail_cli, "call_api", side_effect=ValueError("通信失敗")), contextlib.redirect_stdout(output), contextlib.redirect_stderr(error):
            code = mail_cli.main(["examples/emails.json", "--send"])
        self.assertEqual(code, 1)
        self.assertEqual(output.getvalue(), "")

    def test_limit_checked_before_network(self):
        with patch.object(mail_cli, "call_api") as api, contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(mail_cli.main(["examples/emails.json", "--send", "--limit", "2"]), 1)
        api.assert_not_called()


if __name__ == "__main__":
    unittest.main()
