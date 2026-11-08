"""Personal email urgency CLI with project-local .env support."""

import argparse
from datetime import datetime
from email import policy
from email.parser import BytesParser
from html.parser import HTMLParser
import json
import math
import os
from pathlib import Path
import sys
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from dotenv import dotenv_values

from policy import QUESTIONS, classify

ENDPOINT = "https://api.typesafe.ai/v1/systemone"
ENV_FILE = Path(__file__).resolve().with_name(".env")


def api_key(env_file=ENV_FILE):
    """Prefer an explicitly set environment variable; never execute .env contents."""
    if "TYPESAFE_API_KEY" in os.environ:
        return os.environ["TYPESAFE_API_KEY"].strip()
    return (dotenv_values(env_file, interpolate=False).get("TYPESAFE_API_KEY") or "").strip()


class PlainHTML(HTMLParser):
    def __init__(self):
        super().__init__()
        self.parts = []
        self.hidden = 0

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style"):
            self.hidden += 1
        if tag in ("p", "br", "div", "li"):
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag in ("script", "style"):
            self.hidden = max(0, self.hidden - 1)

    def handle_data(self, data):
        if not self.hidden:
            self.parts.append(data)


def load_emails(path):
    if path.suffix.lower() == ".eml":
        message = BytesParser(policy=policy.default).parsebytes(path.read_bytes())
        part = message.get_body(preferencelist=("plain", "html"))
        if part is None:
            raise ValueError("メールに読み取り可能な本文がありません")
        body = part.get_content()
        if part.get_content_type() == "text/html":
            parser = PlainHTML()
            parser.feed(body)
            body = "".join(parser.parts)
        values = [{"id": path.stem, "subject": str(message.get("Subject", "")),
                   "date": str(message.get("Date", "")), "body": body}]
    else:
        values = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(values, list) or not values:
        raise ValueError("入力は1件以上のメールを含むJSON配列にしてください")
    result = []
    for i, item in enumerate(values):
        if not isinstance(item, dict) or not isinstance(item.get("body"), str) or not item["body"].strip():
            raise ValueError(f"メール{i + 1}: 空でないbody文字列が必要です")
        for key in ("id", "subject", "date"):
            if key in item and not isinstance(item[key], str):
                raise ValueError(f"メール{i + 1}: {key}は文字列にしてください")
        # Only these fields leave the computer. No attachments or address headers.
        clean = {key: item.get(key, "") for key in ("subject", "date", "body")}
        if len(clean["body"]) > 20000:
            raise ValueError(f"メール{i + 1}: 本文が20,000文字を超えています。自動切り捨てはしません")
        clean["id"] = item.get("id", str(i + 1))
        result.append(clean)
    return result


def payload_for(mail, now, model):
    return {"model": model, "state": {
        "evaluation_time": now,
        "email": {k: mail[k] for k in ("subject", "date", "body")},
    }, "questions": QUESTIONS}


def call_api(payload, key):
    request = Request(ENDPOINT, data=json.dumps(payload).encode("utf-8"), headers={
        "Authorization": f"Bearer {key}", "Content-Type": "application/json"}, method="POST")
    try:
        with urlopen(request, timeout=45) as response:
            return json.load(response)
    except HTTPError as exc:
        # Do not print provider error bodies or headers, which may contain private data.
        raise ValueError(f"TypeSafe APIエラー HTTP {exc.code}") from None
    except (URLError, TimeoutError):
        raise ValueError("TypeSafe APIへの接続に失敗しました") from None


def probabilities(response):
    if not isinstance(response, dict) or not isinstance(response.get("answers"), dict):
        raise ValueError("API応答にanswersがありません")
    result = {}
    for name in QUESTIONS:
        answer = response["answers"].get(name)
        if not isinstance(answer, dict) or answer.get("type") != "noul":
            raise ValueError(f"API応答の型が不正です: {name}")
        p = answer.get("noul")
        if isinstance(p, bool) or not isinstance(p, (int, float)) or not math.isfinite(p) or not 0 <= p <= 1:
            raise ValueError(f"API応答の確率が不正です: {name}")
        result[name] = p
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description="Jevで私用メールの緊急性を分類します")
    parser.add_argument("input", type=Path, help="JSON配列または.emlファイル")
    parser.add_argument("--send", action="store_true", help="内容をTypeSafe APIに送信します（料金が発生します）")
    parser.add_argument("--limit", type=int, default=10, help="送信件数の上限（既定10件。超過時は送信せず停止）")
    parser.add_argument("--at", help="評価日時。タイムゾーン付きISO 8601形式")
    parser.add_argument("--model", default="jev-latest")
    args = parser.parse_args(argv)
    try:
        now = datetime.fromisoformat(args.at) if args.at else datetime.now().astimezone()
        if now.tzinfo is None or now.utcoffset() is None:
            raise ValueError("--atには+09:00などのタイムゾーンを指定してください")
        mails = load_emails(args.input)
        if args.limit < 1 or len(mails) > args.limit:
            raise ValueError("メール件数が--limitの範囲外です。件数を確認してください")
        key = api_key() if args.send else ""
        if args.send and not key:
            raise ValueError("jev-poc直下の.env、または環境変数にTYPESAFE_API_KEYを設定してください")
        for mail in mails:
            payload = payload_for(mail, now.isoformat(), args.model)
            record = {"id": mail["id"], "subject": mail["subject"]}
            if not args.send:
                record.update(mode="dry-run", request=payload)
            else:
                response = call_api(payload, key)
                p = probabilities(response)
                label, reason = classify(p)
                record.update(label=label, reason=reason, probabilities=p,
                              model=response.get("model"), evaluated_at=now.isoformat(),
                              usage=response.get("usage"))
            print(json.dumps(record, ensure_ascii=False))
        return 0
    except (ValueError, OSError) as exc:
        print(f"エラー: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
