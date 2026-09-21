#!/usr/bin/env python3
"""Use TypeSafe Jev to pre-screen SEC daily change candidates.

Jev does not replace the deterministic candidate rules or the formal editorial
review. It only returns typed, confidence-aware judgments that help decide what
to read first. API failures are fail-open: SEC ingestion and the existing rules
continue to work, while the output records that Jev was unavailable.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


ROOT = Path(__file__).resolve().parent.parent
DEFAULT_INPUT = ROOT / "sec_daily_change_candidates.json"
DEFAULT_OUTPUT = ROOT / "sec_daily_jev_review.json"
DEFAULT_MARKDOWN = ROOT / "60_SEC_Filing_Radar" / "SEC_Daily_Jev_Review.md"
API_URL = "https://api.typesafe.ai/v1/systemone"
DEFAULT_MODEL = "jev-1.13.0"

DIRECTION_LABELS = {
    "risk": "風險",
    "improvement": "改善",
    "conclusion": "可能改變結論",
    "no_material_change": "無實質變化",
}
SOURCE_LABELS = {
    "sufficient_for_priority": "足以安排閱讀優先度",
    "needs_primary_source_review": "需讀官方原文",
    "insufficient": "證據不足",
}
ROUTE_LABELS = {
    "urgent_human_review": "高優先人工覆核",
    "normal_human_review": "一般人工覆核",
    "low_priority_human_review": "低優先人工覆核",
    "api_error": "Jev 無法判讀",
}


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text())


def batch_id(candidates: list[dict[str, Any]]) -> str:
    ids = sorted(str(row.get("id") or "") for row in candidates)
    return hashlib.sha256("|".join(ids).encode()).hexdigest()[:12]


def candidate_state(candidate: dict[str, Any]) -> dict[str, Any]:
    """Keep state narrow; Jev performs best without unrelated filing text."""
    return {
        "task": "Pre-screen one SEC research candidate for human review. Do not give investment advice.",
        "candidate": {
            "ticker": candidate.get("ticker"),
            "rule_classification": candidate.get("type"),
            "rule_key": candidate.get("rule_key"),
            "headline": candidate.get("headline"),
            "evidence": list(candidate.get("evidence") or [])[:12],
            "why_candidate": candidate.get("why_candidate"),
            "filing_date": candidate.get("filing_date"),
            "materiality_facts": candidate.get("materiality") or {},
            "source_labels": [row.get("label") for row in candidate.get("sources") or []],
        },
    }


def questions() -> dict[str, Any]:
    return {
        "direction": {
            "type": "choice",
            "instructions": (
                "Based only on candidate.evidence and materiality_facts, which direction best describes "
                "the possible change to a long-term investment thesis? Classify uncertainty or a filing "
                "that merely requires rereading as conclusion, not automatically as risk."
            ),
            "criteria": {
                "risk": "Evidence points to deterioration, dilution, governance concern, or thesis invalidation.",
                "improvement": "Evidence points to a concrete improvement or stronger thesis support.",
                "conclusion": "Evidence may change the conclusion but its direction is mixed or not established.",
                "no_material_change": "Evidence is routine, duplicative, or unlikely to affect the long-term thesis.",
            },
        },
        "materiality": {
            "type": "score",
            "instructions": (
                "How important is this candidate for deciding the order in which a long-term investor should "
                "read the underlying official filing? Judge semantic importance, not exact arithmetic."
            ),
            "criteria": [
                "Low: routine or weak signal; unlikely to change the thesis.",
                "Moderate: worth reviewing but not time-sensitive.",
                "High: could materially change risk, financial quality, dilution, governance, or the thesis.",
                "Critical: potentially thesis-breaking or requires immediate official-source verification.",
            ],
        },
        "source_sufficiency": {
            "type": "choice",
            "instructions": "Is the supplied evidence sufficient only for assigning a reading priority?",
            "criteria": {
                "sufficient_for_priority": "Enough context to assign priority, while not treating it as a final conclusion.",
                "needs_primary_source_review": "The SEC filing or exhibit must be read before even the direction is trusted.",
                "insufficient": "The supplied state is too incomplete or ambiguous to use.",
            },
        },
        "long_term_relevance": {
            "type": "noul",
            "instructions": (
                "Does the supplied evidence plausibly affect a long-term investor's view of financial quality, "
                "competitive position, governance, dilution, capital allocation, or thesis validity?"
            ),
        },
    }


def call_jev(api_key: str, state: dict[str, Any], model: str, timeout: float) -> dict[str, Any]:
    payload = json.dumps({"state": state, "model": model, "questions": questions()}).encode()
    request = Request(
        API_URL,
        data=payload,
        method="POST",
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "User-Agent": "sec-kb-jev-review/1.0",
        },
    )
    try:
        with urlopen(request, timeout=timeout) as response:
            return json.loads(response.read().decode())
    except HTTPError as error:
        detail = error.read().decode(errors="replace")[:300]
        raise RuntimeError(f"TypeSafe HTTP {error.code}: {detail}") from error
    except (URLError, TimeoutError) as error:
        raise RuntimeError(f"TypeSafe connection error: {error}") from error


def answer_confidence(answer: dict[str, Any]) -> float | None:
    value = answer.get("confidence")
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def clamp_probability(value: Any) -> float | None:
    try:
        return max(0.0, min(1.0, float(value)))
    except (TypeError, ValueError):
        return None


def normalize_review(candidate: dict[str, Any], response: dict[str, Any]) -> dict[str, Any]:
    answers = response.get("answers") or {}
    direction_answer = answers.get("direction") or {}
    materiality_answer = answers.get("materiality") or {}
    source_answer = answers.get("source_sufficiency") or {}
    relevance_answer = answers.get("long_term_relevance") or {}

    direction = direction_answer.get("choice") or "no_material_change"
    source_sufficiency = source_answer.get("choice") or "insufficient"
    try:
        materiality_score = float(materiality_answer.get("score"))
    except (TypeError, ValueError):
        materiality_score = 0.0
    relevance = clamp_probability(relevance_answer.get("noul"))
    confidences = [
        value for value in (
            answer_confidence(direction_answer),
            answer_confidence(materiality_answer),
            answer_confidence(source_answer),
        ) if value is not None
    ]
    confidence_floor = min(confidences) if confidences else None
    disagreement = direction not in {candidate.get("type"), "conclusion"}
    uncertain = confidence_floor is None or confidence_floor < 0.70

    if materiality_score >= 2 and (relevance or 0) >= 0.65:
        route = "urgent_human_review"
    elif direction == "no_material_change" and materiality_score < 1 and (relevance or 0) < 0.5:
        route = "low_priority_human_review"
    else:
        route = "normal_human_review"
    if disagreement or uncertain or source_sufficiency != "sufficient_for_priority":
        route = "urgent_human_review" if materiality_score >= 2 else "normal_human_review"

    return {
        "candidate_id": candidate.get("id"),
        "ticker": candidate.get("ticker"),
        "rule_direction": candidate.get("type"),
        "jev_direction": direction,
        "jev_direction_label": DIRECTION_LABELS.get(direction, direction),
        "materiality_score": round(materiality_score, 3),
        "materiality_label": ["低", "中", "高", "重大"][max(0, min(3, round(materiality_score)))],
        "long_term_relevance_probability": relevance,
        "source_sufficiency": source_sufficiency,
        "source_sufficiency_label": SOURCE_LABELS.get(source_sufficiency, source_sufficiency),
        "confidence_floor": None if confidence_floor is None else round(confidence_floor, 4),
        "direction_disagrees_with_rule": disagreement,
        "uncertain": uncertain,
        "route": route,
        "route_label": ROUTE_LABELS[route],
        "requires_human_review": True,
        "probabilities": {
            "direction": direction_answer.get("probabilities") or {},
            "materiality": materiality_answer.get("probabilities") or {},
            "source_sufficiency": source_answer.get("probabilities") or {},
        },
    }


def build_payload(candidates_payload: dict[str, Any], api_key: str | None,
                  model: str = DEFAULT_MODEL, timeout: float = 15.0,
                  caller=call_jev) -> dict[str, Any]:
    candidates = list(candidates_payload.get("candidates") or [])
    payload: dict[str, Any] = {
        "schema_version": 1,
        "candidate_batch_id": batch_id(candidates),
        "candidate_generated_at": candidates_payload.get("generated_at"),
        "reviewed_at": None,
        "model_requested": model,
        "models_used": [],
        "status": "no_candidates" if not candidates else "pending",
        "candidate_count": len(candidates),
        "reviewed_count": 0,
        "failed_count": 0,
        "policy": (
            "Jev 只做結構化預判與閱讀路由；不計算財務數字、不改寫正式綜合結論，"
            "且所有候選仍須人工核對 SEC 官方原文。"
        ),
        "reviews": [],
        "errors": [],
    }
    if not candidates:
        return payload
    if not api_key:
        payload["status"] = "skipped_missing_api_key"
        return payload

    models_used = set()
    for candidate in candidates:
        try:
            response = caller(api_key, candidate_state(candidate), model, timeout)
            review = normalize_review(candidate, response)
            review["model"] = response.get("model") or model
            models_used.add(review["model"])
            payload["reviews"].append(review)
        except Exception as error:  # fail-open by design; never block SEC ingestion
            payload["errors"].append({
                "candidate_id": candidate.get("id"),
                "ticker": candidate.get("ticker"),
                "error": str(error)[:400],
            })
    payload["reviewed_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    payload["reviewed_count"] = len(payload["reviews"])
    payload["failed_count"] = len(payload["errors"])
    payload["models_used"] = sorted(models_used)
    payload["status"] = (
        "complete" if payload["reviewed_count"] == len(candidates)
        else "api_error" if not payload["reviewed_count"]
        else "partial_failure"
    )
    return payload


def render_markdown(payload: dict[str, Any]) -> str:
    lines = [
        "---",
        "title: SEC 每日 Jev 預判",
        f"candidate_generated_at: {payload.get('candidate_generated_at')}",
        f"reviewed_at: {payload.get('reviewed_at')}",
        "tags:",
        "  - sec/daily",
        "  - ai/jev-prescreen",
        "---",
        "",
        "# SEC 每日 Jev 預判",
        "",
        "> Jev 只負責候選分類、重要性與閱讀路由；不是正式投資結論，也不取代 SEC 官方原文。",
        "",
        f"- 狀態：**{payload.get('status')}**",
        f"- 候選／完成／失敗：**{payload.get('candidate_count', 0)}／{payload.get('reviewed_count', 0)}／{payload.get('failed_count', 0)}**",
        f"- 模型：**{', '.join(payload.get('models_used') or [payload.get('model_requested') or '—'])}**",
        "",
    ]
    for row in payload.get("reviews") or []:
        confidence = row.get("confidence_floor")
        confidence_text = "—" if confidence is None else f"{confidence * 100:.0f}%"
        relevance = row.get("long_term_relevance_probability")
        relevance_text = "—" if relevance is None else f"{relevance * 100:.0f}%"
        lines += [
            f"## {row.get('ticker')}｜{row.get('route_label')}",
            "",
            f"- 方向：{row.get('jev_direction_label')}（規則原分類：{row.get('rule_direction')}）",
            f"- 重要性：{row.get('materiality_label')}（{row.get('materiality_score')}／3）",
            f"- 長期相關機率：{relevance_text}",
            f"- 信心下限：{confidence_text}",
            f"- 證據：{row.get('source_sufficiency_label')}",
            "- 結論：仍須人工閱讀 SEC 官方原文。",
            "",
        ]
    if not payload.get("reviews"):
        lines += ["目前沒有可供 Jev 預判的新候選，或 API key 尚未設定。", ""]
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--markdown", type=Path, default=DEFAULT_MARKDOWN)
    parser.add_argument("--model", default=os.environ.get("TYPESAFE_DEFAULT_MODEL", DEFAULT_MODEL))
    parser.add_argument("--timeout", type=float, default=15.0)
    args = parser.parse_args()

    candidates = load_json(args.input)
    payload = build_payload(candidates, os.environ.get("TYPESAFE_API_KEY"), args.model, args.timeout)
    args.output.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n")
    args.markdown.parent.mkdir(parents=True, exist_ok=True)
    args.markdown.write_text(render_markdown(payload))
    print(
        f"Jev pre-screen: {payload['status']} | "
        f"{payload['reviewed_count']}/{payload['candidate_count']} reviewed | "
        f"{payload['failed_count']} failed"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
