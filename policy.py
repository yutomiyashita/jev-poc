"""Auditable questions and classification policy for personal mail."""

YES = 0.7
NO = 0.3


def noul(question, yes, no):
    return {"type": "noul", "instructions": question,
            "criteria": {"true": yes, "false": no}}


QUESTIONS = {
    "action_needed": noul(
        "Does this email describe an outstanding action the recipient needs to take?",
        "A personal obligation, reply, appointment change, payment, or account issue needs attention.",
        "A receipt, completed transaction, general newsletter, or optional promotional offer."),
    "immediate": noul(
        "Does the recipient's outstanding action need attention within the next two hours?",
        "The current situation requires attention within two hours of evaluation_time, such as an imminent appointment change or ongoing account compromise.",
        "The action can wait beyond two hours. An expired promotional offer does not require action."),
    "today": noul(
        "Does the recipient's outstanding action need attention before the end of today?",
        "A real obligation needs attention by the end of the calendar day at evaluation_time. Resolve relative dates using the email date, not the evaluation date.",
        "The obligation can wait until a later day, or the message only advertises an optional sale."),
    "serious_impact": noul(
        "Does delaying the outstanding action risk a substantial negative consequence for the recipient?",
        "Account compromise, loss of essential service, a significant financial penalty, or missing an important appointment.",
        "A minor inconvenience or missing an optional discount. The email describes an already resolved issue."),
}


def classify(p):
    """Uncertain relevant answers require review, rather than silently becoming no."""
    if p["action_needed"] <= NO:
        if any(p[k] >= YES for k in ("immediate", "today", "serious_impact")):
            return "判断保留", "対応不要と緊急性の判定が矛盾しています"
        return "対応不要", "対応が必要である可能性が低いと判定されました"
    if p["action_needed"] < YES:
        return "判断保留", "対応が必要か判断が分かれています"
    if p["immediate"] >= YES:
        return "緊急", "2時間以内の対応が必要と判定されました"
    if p["today"] >= YES or p["serious_impact"] >= YES:
        return "高", "今日中の対応、または遅延による大きな影響が見込まれます"
    if any(p[k] > NO for k in ("immediate", "today", "serious_impact")):
        return "判断保留", "期限または遅延の影響を確定できません"
    return "通常", "対応は必要ですが、急ぐ根拠は低いと判定されました"
