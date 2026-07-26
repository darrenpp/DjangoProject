from dataclasses import dataclass
from difflib import SequenceMatcher

from apps.dashboard.assistant_memory import (
    assistant_memory_rows,
    retrieve_assistant_sources,
    serialize_sources,
)
from apps.dashboard.assistant_scope_context import MEDICAL_OFFICE_TERMS, NURSING_OFFICE_TERMS
from apps.dashboard.ai_provider import AIProviderError, ai_provider_status, call_configured_ai_json


@dataclass(frozen=True)
class HelpdeskAnswer:
    title: str
    keywords: tuple[str, ...]
    answer: str
    links: tuple[tuple[str, str], ...] = ()


HELPDESK_KNOWLEDGE = (
    HelpdeskAnswer(
        title="Create an applicant account",
        keywords=("register account", "create account", "sign up", "new user", "login", "password"),
        answer=(
            "To start, create an applicant account from the registration page. Use your correct name, "
            "email or phone number, role type, and registration or licence number if you already have one. "
            "After logging in, the system will send you to the dashboard that matches your role."
        ),
        links=(("Create applicant account", "register"), ("Login", "login")),
    ),
    HelpdeskAnswer(
        title="Nursing Council form selection",
        keywords=("nursing form", "nurse form", "nc1", "nc2", "nc3", "full license", "full licence", "renewal", "provisional"),
        answer=(
            "For Nursing Council applications, choose the form that matches your pathway. NC1 is for provisional "
            "licence, NC2 is for full licence, and NC3 is for renewal. If you are unsure, open the Nursing Forms "
            "page and read the pathway guide before submitting."
        ),
        links=(("Open Nursing Forms", "public_nurse_register"), ("Fee Structure and Guidelines", "fee_structure")),
    ),
    HelpdeskAnswer(
        title="Medical Board forms",
        keywords=("medical board", "doctor", "specialist", "chw", "community health worker", "facility checklist", "medical form"),
        answer=(
            "Medical Board users should use the Medical Board forms for doctors, specialists, CHWs, renewals, "
            "facility accreditation, private health facility checks, and training college facility checks. "
            "These records are managed separately in the Medical Board portal but still feed the central registry."
        ),
        links=(("Open Medical Board Forms", "medical_board_register"), ("Medical Board Portal", "medical_board_portal")),
    ),
    HelpdeskAnswer(
        title="Required supporting documents",
        keywords=("documents", "attachments", "upload", "certificate", "id", "passport", "receipt", "qualification"),
        answer=(
            "Most applications need identity evidence, qualification certificates, payment receipt details, "
            "and any competency or employer documents required by the selected form. Upload clear files and "
            "make sure names, dates, and licence numbers match your profile."
        ),
        links=(("Fee Structure and Guidelines", "fee_structure"),),
    ),
    HelpdeskAnswer(
        title="Payment and receipt help",
        keywords=("payment", "receipt", "official receipt", "fee", "fees", "amount", "treasury", "atp"),
        answer=(
            "Keep your official receipt number and receipt image ready before submitting payment details. "
            "The registrar can review the receipt record, mark it completed, and link it to your application."
        ),
        links=(("Fee Structure and Guidelines", "fee_structure"),),
    ),
    HelpdeskAnswer(
        title="Application status and review",
        keywords=("status", "pending", "approved", "rejected", "review", "under review", "application progress"),
        answer=(
            "After submission, your application may show as pending or under review until a registrar checks it. "
            "If more information is needed, the system can flag your record and send a notification to your profile."
        ),
        links=(("Messages and Enquiries", "enquiry_inbox"),),
    ),
    HelpdeskAnswer(
        title="Missing information alerts",
        keywords=("missing", "incomplete", "profile", "alert", "notification", "email", "missing data"),
        answer=(
            "If important profile or licence information is missing, the system places the record under review "
            "and sends a dashboard notification. Update your profile and provide the missing information so the "
            "registrar can complete the review."
        ),
        links=(("My Profile", "user_profile"), ("Messages and Enquiries", "enquiry_inbox")),
    ),
    HelpdeskAnswer(
        title="Licence expiry and renewal",
        keywords=("expire", "expiry", "expired", "renew", "renewal", "six months", "6 months"),
        answer=(
            "Provisional licences are time limited, and full licences must be renewed before expiry. "
            "When a licence is near expiry, the system can show a reminder and notify the user to apply for renewal."
        ),
        links=(("Open Nursing Forms", "public_nurse_register"), ("Messages and Enquiries", "enquiry_inbox")),
    ),
    HelpdeskAnswer(
        title="Contact a registrar",
        keywords=("contact", "help", "enquiry", "message", "registrar", "support", "human"),
        answer=(
            "If the assistant cannot solve the issue, create an enquiry. The message will be routed to the "
            "Nursing Council, Medical Board, or General Registry team depending on the topic."
        ),
        links=(("Create Enquiry", "enquiry_create"), ("Messages and Enquiries", "enquiry_inbox")),
    ),
)


DEFAULT_ANSWER = HelpdeskAnswer(
    title="General help",
    keywords=(),
    answer=(
        "I can help with account registration, Nursing Council forms, Medical Board forms, required documents, "
        "payments, application status, missing data alerts, and licence renewal. Try asking something like "
        "'Which form is for full licence?' or 'What documents do I upload?'."
    ),
    links=(("Nursing Forms", "public_nurse_register"), ("Create Enquiry", "enquiry_create")),
)


HELPDESK_AI_RESPONSE_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "title": {"type": "string"},
        "answer": {"type": "string"},
        "links": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "label": {"type": "string"},
                    "url": {"type": "string"},
                },
                "required": ["label", "url"],
            },
            "maxItems": 4,
        },
        "suggestions": {
            "type": "array",
            "items": {"type": "string"},
            "maxItems": 4,
        },
        "sources": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "label": {"type": "string"},
                    "detail": {"type": "string"},
                    "url": {"type": "string"},
                },
                "required": ["label", "detail", "url"],
            },
            "maxItems": 6,
        },
    },
    "required": ["title", "answer", "links", "suggestions"],
}


def _score_question(question: str, answer: HelpdeskAnswer) -> float:
    question = question.lower()
    score = 0.0
    for keyword in answer.keywords:
        keyword_text = keyword.lower()
        if keyword_text in question:
            score += 3.0 + min(len(keyword_text), 20) / 20
        else:
            score += SequenceMatcher(None, question, keyword_text).ratio()
    return score


def get_helpdesk_response(question: str) -> tuple[HelpdeskAnswer, list[HelpdeskAnswer]]:
    cleaned = " ".join((question or "").strip().split())
    if not cleaned:
        return DEFAULT_ANSWER, list(HELPDESK_KNOWLEDGE[:4])

    ranked = sorted(
        HELPDESK_KNOWLEDGE,
        key=lambda item: _score_question(cleaned, item),
        reverse=True,
    )
    best = ranked[0] if ranked and _score_question(cleaned, ranked[0]) >= 1.25 else DEFAULT_ANSWER
    suggestions = [item for item in ranked[:4] if item.title != best.title]
    return best, suggestions


def _helpdesk_knowledge_payload():
    return [
        {
            "title": item.title,
            "keywords": list(item.keywords),
            "answer": item.answer,
            "link_labels": [label for label, _url_name in item.links],
        }
        for item in HELPDESK_KNOWLEDGE
    ]


def public_helpdesk_sources(question, *, browser_session_key=""):
    text = " ".join(str(question or "").lower().split())
    has_nursing = any(term in text for term in NURSING_OFFICE_TERMS)
    has_medical = any(term in text for term in MEDICAL_OFFICE_TERMS)
    source_scope = "all"
    if has_nursing and not has_medical:
        source_scope = "nursing"
    elif has_medical and not has_nursing:
        source_scope = "medical"
    sources = retrieve_assistant_sources(question=question, scope=source_scope, public=True)
    memory_rows = assistant_memory_rows(
        assistant_kind="public_helpdesk",
        browser_session_key=browser_session_key,
        scope="public",
    )
    if memory_rows and any(token in (question or "").lower() for token in ("remember", "earlier", "last question", "previous")):
        sources.append({
            "label": "Public helpdesk conversation memory",
            "detail": "Recent public helpdesk messages in this browser session.",
            "url": "",
        })
    return serialize_sources(sources)


def maybe_generate_live_helpdesk_response(question: str, local_payload: dict, *, browser_session_key="") -> dict:
    status = ai_provider_status()
    local_payload["ai_provider"] = status
    local_payload["sources"] = public_helpdesk_sources(question, browser_session_key=browser_session_key)
    if status["mode"] != "google_adk":
        return local_payload

    system_prompt = (
        "You are the public registration AI Helpdesk for a government health regulatory platform. "
        "Answer only questions about account registration, Nursing Council forms, Medical Board forms, "
        "documents, payments, application status, missing information alerts, renewals, and contacting a registrar. "
        "Do not expose private records, do not claim an application was approved, and do not invent requirements. "
        "Keep Nursing Council and Medical Board pathways separate. If a question is about nurses, midwives, "
        "nurse aides, graduands, NC forms, or ATP, answer as Nursing Council guidance. If it is about doctors, "
        "specialists, CHW, or Medical Board facilities, answer as Medical Board guidance. "
        "Use the supplied helpdesk knowledge and local fallback answer."
    )
    try:
        live_payload = call_configured_ai_json(
            system_prompt=system_prompt,
            user_payload={
                "question": question,
                "knowledge_base": _helpdesk_knowledge_payload(),
                "local_fallback_answer": local_payload,
                "public_sources": local_payload["sources"],
            },
            schema=HELPDESK_AI_RESPONSE_SCHEMA,
            schema_name="public_helpdesk_response",
        )
    except AIProviderError as exc:
        local_payload["ai_provider"] = {
            **status,
            "mode": "local_fallback",
            "label": "Local Offline Assistant",
            "detail": f"Public helpdesk fallback used: {exc}",
        }
        return local_payload

    allowed_links = {
        link["url"]: link
        for link in local_payload.get("links", [])
        if isinstance(link, dict) and link.get("url")
    }
    live_links = [
        allowed_links[link.get("url")]
        for link in live_payload.get("links", [])
        if isinstance(link, dict) and link.get("url") in allowed_links
    ]
    live_payload["links"] = live_links or local_payload.get("links", [])
    live_payload["sources"] = serialize_sources(live_payload.get("sources") or local_payload.get("sources") or [])
    live_payload["ai_provider"] = status
    return live_payload
