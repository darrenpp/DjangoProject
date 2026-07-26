"""Declarative routing and safety contracts for the Regulatory AI layer.

This module deliberately does *not* import a Django model, ORM manager, model
provider, RAG implementation, or an agent SDK.  It is a small policy boundary
between a conversational interface and the separately implemented, audited
tools that may later be exposed through Google ADK, LangGraph, or another
gateway.

The supervisor can select an operational speciality, but it cannot execute a
query, call an LLM, change a registry record, approve a workflow, or train on
conversation data.  A gateway must independently enforce each declared tool
contract before it invokes an actual read-only service.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Mapping

from apps.dashboard.access import (
    is_data_quality_reviewer,
    is_finance_reviewer,
    is_medical_board_staff,
    is_nursing_council_staff,
)


SUPERVISOR_ID = "regulatory_ai_supervisor"
SCOPE_ALL = "all"
SCOPE_MEDICAL = "medical"
SCOPE_NURSING = "nursing"
SCOPE_RESTRICTED = "restricted"
VALID_SCOPES = {SCOPE_ALL, SCOPE_MEDICAL, SCOPE_NURSING, SCOPE_RESTRICTED}

DATA_PUBLIC_POLICY = "public_policy"
DATA_AGGREGATE_GOVERNED = "aggregate_governed"
DATA_ROLE_SCOPED_REGISTRY = "role_scoped_registry"
DATA_STAGING_ONLY = "staging_only"
DATA_RESTRICTED = "restricted"


@dataclass(frozen=True)
class ToolContract:
    """A capability declaration for a separately authorised read-only tool."""

    name: str
    purpose: str
    data_classification: str
    allowed_scopes: tuple[str, ...]
    constraints: tuple[str, ...] = ()
    requires_explicit_identifier: bool = False
    citations_required: bool = False
    human_approval_required: bool = False
    supports_all_office_scope: bool = True

    def is_available_for(self, scope: str) -> bool:
        if scope not in self.allowed_scopes:
            return False
        return scope != SCOPE_ALL or self.supports_all_office_scope

    def as_dict(self, scope: str) -> dict:
        """Return a JSON-safe contract for a gateway or UI response."""

        return {
            "name": self.name,
            "purpose": self.purpose,
            "data_classification": self.data_classification,
            "read_only": True,
            "scope": scope,
            "requires_explicit_identifier": self.requires_explicit_identifier,
            "citations_required": self.citations_required,
            "human_approval_required": self.human_approval_required,
            "constraints": list(self.constraints),
        }


@dataclass(frozen=True)
class RegulatoryAIAgent:
    """A named specialist known to the supervisor.

    The ``tools`` are contracts only.  They are not callable functions and are
    intentionally kept free of query strings, user identifiers, raw records,
    and provider configuration.
    """

    identifier: str
    label: str
    description: str
    tools: tuple[ToolContract, ...]
    response_constraints: tuple[str, ...]


@dataclass(frozen=True)
class RegulatoryAIToolRoute:
    """A safe plan returned by the supervisor before any tool execution."""

    status: str
    supervisor: str
    agent: RegulatoryAIAgent | None
    supporting_agents: tuple[RegulatoryAIAgent, ...]
    scope: str
    requested_domain: str
    intent_scores: Mapping[str, int]
    routing_reason: str
    allowed_tools: tuple[ToolContract, ...]
    data_classifications: tuple[str, ...]
    response_constraints: tuple[str, ...]

    @property
    def requires_citations(self) -> bool:
        return any(tool.citations_required for tool in self.allowed_tools)

    @property
    def requires_human_approval(self) -> bool:
        return any(tool.human_approval_required for tool in self.allowed_tools)

    def as_dict(self) -> dict:
        """Serialize the route without accidentally exposing executable tools."""

        return {
            "status": self.status,
            "supervisor": self.supervisor,
            "agent": (
                {
                    "id": self.agent.identifier,
                    "label": self.agent.label,
                    "description": self.agent.description,
                }
                if self.agent
                else None
            ),
            "supporting_agents": [
                {"id": agent.identifier, "label": agent.label}
                for agent in self.supporting_agents
            ],
            "scope": self.scope,
            "requested_domain": self.requested_domain,
            "routing_reason": self.routing_reason,
            "intent_scores": dict(self.intent_scores),
            "execution_mode": "contract_only",
            "direct_database_access": False,
            "direct_llm_access": False,
            "allowed_tools": [tool.as_dict(self.scope) for tool in self.allowed_tools],
            "data_classifications": list(self.data_classifications),
            "requires_citations": self.requires_citations,
            "requires_human_approval": self.requires_human_approval,
            "response_constraints": list(self.response_constraints),
            "prohibited_capabilities": list(PROHIBITED_CAPABILITIES),
        }


COMMON_READ_ONLY_CONSTRAINTS = (
    "Read-only decision support; never approve, reject, suspend, or alter an official record.",
    "Use the caller's regulatory-office scope on every downstream query.",
    "Return only the minimum data needed for the question and apply personal-data redaction.",
    "Treat any result as decision support and route formal decisions through the existing workflow.",
)

PROHIBITED_CAPABILITIES = (
    "direct_database_access",
    "raw_sql_or_unscoped_orm_queries",
    "direct_llm_provider_access",
    "write_or_promote_registry_records",
    "approve_or_reject_regulatory_workflows",
    "expose_raw_chats_or_sensitive_registry_exports",
    "train_on_conversation_or_registry_data",
)


def _tool(
    name: str,
    purpose: str,
    data_classification: str,
    scopes: tuple[str, ...] = (SCOPE_NURSING, SCOPE_MEDICAL, SCOPE_ALL),
    *,
    constraints: tuple[str, ...] = (),
    requires_explicit_identifier: bool = False,
    citations_required: bool = False,
    human_approval_required: bool = False,
    supports_all_office_scope: bool = True,
) -> ToolContract:
    return ToolContract(
        name=name,
        purpose=purpose,
        data_classification=data_classification,
        allowed_scopes=scopes,
        constraints=constraints,
        requires_explicit_identifier=requires_explicit_identifier,
        citations_required=citations_required,
        human_approval_required=human_approval_required,
        supports_all_office_scope=supports_all_office_scope,
    )


AGENT_REGISTRY: dict[str, RegulatoryAIAgent] = {
    "data_quality": RegulatoryAIAgent(
        identifier="data_quality",
        label="Data Quality Agent",
        description="Reviews governed staging quality, duplicates, missing fields, and import validation signals.",
        tools=(
            _tool(
                "get_staged_import_quality_summary",
                "Read aggregate validation, completeness, and import-stage counts.",
                DATA_STAGING_ONLY,
                constraints=(
                    "Use staged or review records only; never promote a record.",
                    "Return aggregate counts and redacted review references, not raw spreadsheet rows.",
                ),
            ),
            _tool(
                "get_duplicate_candidate_summary",
                "Read bounded duplicate-detection candidates and confidence bands.",
                DATA_STAGING_ONLY,
                constraints=(
                    "Duplicate suggestions require human review before any merge or correction.",
                    "Do not disclose identity fields beyond the authorised review surface.",
                ),
                human_approval_required=True,
            ),
            _tool(
                "get_missing_data_summary",
                "Read aggregate missing-data and validation-rule outcomes.",
                DATA_AGGREGATE_GOVERNED,
                constraints=("Do not infer or fabricate missing personal or regulatory facts.",),
            ),
        ),
        response_constraints=COMMON_READ_ONLY_CONSTRAINTS
        + (
            "Describe duplicate detection as a review recommendation, not an automatic merge.",
        ),
    ),
    "registration": RegulatoryAIAgent(
        identifier="registration",
        label="Registration Agent",
        description="Explains registration, licence, renewal, ATP, and application-review status using scoped records.",
        tools=(
            _tool(
                "get_registration_workflow_summary",
                "Read aggregate registration, renewal, licence, and application queue metrics.",
                DATA_AGGREGATE_GOVERNED,
                constraints=("Use published workflow status only; do not determine legal eligibility.",),
            ),
            _tool(
                "search_scoped_registration_records",
                "Perform a bounded, role-scoped, read-only registry lookup through the approved record tool.",
                DATA_ROLE_SCOPED_REGISTRY,
                constraints=(
                    "Require a focused name, registration number, licence number, or reference before lookup.",
                    "Use the existing office-scoped queryset and redacted display fields.",
                    "Return at most the platform-approved bounded result count.",
                    "For all-office staff, preserve Nursing and Medical Board results as separate domains.",
                ),
                requires_explicit_identifier=True,
            ),
            _tool(
                "get_renewal_due_summary",
                "Read aggregate upcoming-renewal and ATP/licence-due metrics.",
                DATA_AGGREGATE_GOVERNED,
                constraints=("Never issue, renew, expire, or suspend a licence from an AI response.",),
            ),
        ),
        response_constraints=COMMON_READ_ONLY_CONSTRAINTS
        + (
            "Individual lookup results must not be retained as model-training or chat-memory content.",
        ),
    ),
    "workforce_analytics": RegulatoryAIAgent(
        identifier="workforce_analytics",
        label="Workforce Analytics Agent",
        description="Uses approved aggregate snapshots for workforce distribution, retirement, shortages, and forecasts.",
        tools=(
            _tool(
                "get_workforce_distribution_aggregate",
                "Read governed aggregate workforce distribution by authorised geography, cadre, specialty, or facility.",
                DATA_AGGREGATE_GOVERNED,
                constraints=(
                    "Suppress or aggregate small cells according to the reporting policy.",
                    "Do not join individual age, workplace, or identity records in an answer.",
                ),
            ),
            _tool(
                "get_workforce_forecast_snapshot",
                "Read a versioned, approved shortage or retirement forecast snapshot.",
                DATA_AGGREGATE_GOVERNED,
                constraints=(
                    "Only use a documented forecast version, observation date, and data-coverage note.",
                    "Describe predictions as planning signals, not facts or staffing directives.",
                ),
                citations_required=True,
            ),
            _tool(
                "get_facility_staffing_gap_aggregate",
                "Read approved facility staffing targets and aggregate observed gaps.",
                DATA_AGGREGATE_GOVERNED,
                constraints=(
                    "Report a gap only where an approved staffing target exists.",
                    "Do not infer rural classification, population need, or target staffing level.",
                ),
            ),
        ),
        response_constraints=COMMON_READ_ONLY_CONSTRAINTS
        + (
            "Always state data coverage, source date, and forecast limitations when available.",
        ),
    ),
    "policy_document": RegulatoryAIAgent(
        identifier="policy_document",
        label="Policy and Document Agent",
        description="Retrieves authoritative policies, guidelines, FAQs, forms, standards, and published regulatory material.",
        tools=(
            _tool(
                "search_authoritative_knowledge",
                "Search the approved, scope-filtered knowledge index for published regulatory sources.",
                DATA_PUBLIC_POLICY,
                constraints=(
                    "Cite the authoritative source title and reference for every material answer.",
                    "Do not use raw chat history, unapproved drafts, or unrestricted documents as authority.",
                ),
                citations_required=True,
            ),
            _tool(
                "get_document_governance_metadata",
                "Read document currency, approval, owner, and access-policy metadata.",
                DATA_PUBLIC_POLICY,
                constraints=(
                    "Apply document access policy before any content retrieval.",
                    "Flag superseded or unapproved material instead of treating it as policy.",
                ),
                citations_required=True,
            ),
        ),
        response_constraints=COMMON_READ_ONLY_CONSTRAINTS
        + (
            "Give policy guidance with sources; do not substitute for Board, legal, or clinical decisions.",
        ),
    ),
    "compliance": RegulatoryAIAgent(
        identifier="compliance",
        label="Compliance Agent",
        description="Surfaces aggregate compliance, credential, accreditation, CPD, and renewal-risk signals.",
        tools=(
            _tool(
                "get_compliance_risk_aggregate",
                "Read aggregate CPD, expiry, credential, and accreditation risk indicators.",
                DATA_AGGREGATE_GOVERNED,
                constraints=(
                    "Do not expose complaint narratives, disciplinary evidence, health details, or case identities.",
                    "Do not calculate or label an individual as non-compliant without an approved workflow decision.",
                ),
            ),
            _tool(
                "get_accreditation_status_summary",
                "Read approved aggregate facility-accreditation status and inspection currency signals.",
                DATA_AGGREGATE_GOVERNED,
                constraints=("Do not grant, suspend, or alter accreditation from an AI response.",),
            ),
            _tool(
                "get_credential_and_privilege_summary",
                "Read aggregate verified-credential and explicit clinical-privilege counts.",
                DATA_AGGREGATE_GOVERNED,
                constraints=(
                    "Never infer a clinical privilege from specialty, qualification, or uploaded evidence.",
                    "Do not disclose individual complaint or disciplinary case information.",
                ),
            ),
        ),
        response_constraints=COMMON_READ_ONLY_CONSTRAINTS
        + (
            "Sensitive conduct and disciplinary matters remain in their controlled case-management workflow.",
        ),
    ),
    "report": RegulatoryAIAgent(
        identifier="report",
        label="Report Agent",
        description="Builds cited, reviewable board briefings and operational report drafts from approved aggregates.",
        tools=(
            _tool(
                "get_approved_report_metrics",
                "Read current, governed aggregate metrics and report freshness metadata.",
                DATA_AGGREGATE_GOVERNED,
                constraints=(
                    "Use only approved metrics with source date and definition.",
                    "Keep Nursing Council and Medical Board figures visibly separate in all-office reports.",
                ),
                citations_required=True,
            ),
            _tool(
                "build_board_briefing_draft",
                "Create a non-binding report draft from supplied approved aggregate metrics.",
                DATA_AGGREGATE_GOVERNED,
                constraints=(
                    "A named authorised officer must review, amend, and approve the draft before distribution.",
                    "Do not include individual registry, complaint, disciplinary, or clinical details.",
                ),
                citations_required=True,
                human_approval_required=True,
            ),
        ),
        response_constraints=COMMON_READ_ONLY_CONSTRAINTS
        + (
            "A report is a draft and must not be represented as a Board decision or official publication until approved.",
        ),
    ),
}


INTENT_KEYWORDS: Mapping[str, tuple[tuple[str, int], ...]] = {
    "data_quality": (
        ("duplicate", 4),
        ("deduplicate", 4),
        ("data quality", 4),
        ("missing data", 3),
        ("invalid", 2),
        ("cleanse", 3),
        ("cleansing", 3),
        ("staging", 3),
        ("import", 2),
        ("spreadsheet", 2),
        ("excel", 2),
        ("validation", 2),
    ),
    "registration": (
        ("registration", 3),
        ("register", 2),
        ("renewal", 3),
        ("renew", 3),
        ("licence", 3),
        ("license", 3),
        ("atp", 4),
        ("authority to practice", 4),
        ("application", 2),
        ("practitioner", 1),
        ("registration number", 4),
    ),
    "workforce_analytics": (
        ("workforce", 4),
        ("shortage", 4),
        ("staffing gap", 4),
        ("retire", 4),
        ("retirement", 4),
        ("forecast", 3),
        ("prediction", 3),
        ("province", 2),
        ("district", 2),
        ("distribution", 3),
        ("rural", 2),
        ("specialist", 2),
        ("density", 3),
        ("age group", 3),
        ("under 35", 2),
    ),
    "policy_document": (
        ("policy", 4),
        ("guideline", 4),
        ("standard", 3),
        ("requirement", 3),
        ("requirements", 3),
        ("form", 2),
        ("faq", 3),
        ("document", 3),
        ("act", 3),
        ("legislation", 4),
        ("source", 2),
        ("sources", 2),
        ("explain", 1),
    ),
    "compliance": (
        ("compliance", 4),
        ("complaint", 4),
        ("disciplinary", 4),
        ("discipline", 3),
        ("accreditation", 4),
        ("credential", 4),
        ("privilege", 4),
        ("cpd", 3),
        ("inspection", 3),
        ("risk", 2),
        ("expired", 2),
        ("expiry", 2),
    ),
    "report": (
        ("board report", 5),
        ("board briefing", 5),
        ("briefing", 4),
        ("meeting pack", 5),
        ("report", 3),
        ("summary", 2),
        ("dashboard", 2),
        ("presentation", 3),
    ),
}

INTENT_TIE_BREAK_ORDER = (
    "report",
    "data_quality",
    "compliance",
    "workforce_analytics",
    "policy_document",
    "registration",
)

NURSING_DOMAIN_TOKENS = (
    "nursing council",
    "nursing",
    "nurse",
    "midwife",
    "nurse aide",
    "atp",
)
MEDICAL_DOMAIN_TOKENS = (
    "medical board",
    "doctor",
    "medical practitioner",
    "specialist",
    "clinical privilege",
    "community health worker",
    "chw",
)


def _clean_question(question: object) -> str:
    return " ".join(str(question or "").lower().split())


def _has_required_staff_approval(user: object) -> bool:
    checker = getattr(user, "has_required_staff_login_approvals", None)
    return bool(checker()) if callable(checker) else True


def resolve_regulatory_ai_scope(user: object) -> str:
    """Return the regulatory-office scope that an authenticated staff user has.

    This is deliberately conservative: public users, professionals, finance
    reviewers, inactive accounts, and unapproved staff receive no AI tool
    contract.  The actual tool implementation must perform its own access
    check again; this router is not an authorisation bypass.
    """

    if not getattr(user, "is_authenticated", False) or not getattr(user, "is_active", False):
        return SCOPE_RESTRICTED
    # ``admin`` already denotes the all-office administrative role throughout
    # the existing Django access layer.  Keep this router aligned with that
    # established scope rather than silently downgrading an active admin to a
    # different access model.  Login approval remains enforced by the account
    # and view layer before a real Staff AI request reaches this contract.
    if getattr(user, "role", "") == "admin":
        return SCOPE_ALL
    if not _has_required_staff_approval(user) or is_finance_reviewer(user):
        return SCOPE_RESTRICTED
    if is_data_quality_reviewer(user):
        return SCOPE_ALL
    if is_medical_board_staff(user):
        return SCOPE_MEDICAL
    if is_nursing_council_staff(user):
        return SCOPE_NURSING
    return SCOPE_RESTRICTED


def classify_question_domain(question: object) -> str:
    """Identify the explicitly named regulatory workspace, if any."""

    normalized = _clean_question(question)
    nursing = any(token in normalized for token in NURSING_DOMAIN_TOKENS)
    medical = any(token in normalized for token in MEDICAL_DOMAIN_TOKENS)
    if nursing and medical:
        return SCOPE_ALL
    if nursing:
        return SCOPE_NURSING
    if medical:
        return SCOPE_MEDICAL
    return ""


def score_regulatory_ai_intents(question: object) -> dict[str, int]:
    """Score transparent keyword intents; no model or external service is used."""

    normalized = _clean_question(question)
    scores = {
        agent_id: sum(weight for phrase, weight in phrases if phrase in normalized)
        for agent_id, phrases in INTENT_KEYWORDS.items()
    }
    # An explicit request for an authoritative policy explanation should not be
    # displaced merely because it also mentions a renewal or registration term.
    # This is still deterministic routing, not an inference by a model.
    if "policy" in normalized and any(
        marker in normalized
        for marker in ("cite", "source", "requirement", "explain", "guideline")
    ):
        scores["policy_document"] += 4
    return scores


def _rank_intents(scores: Mapping[str, int]) -> tuple[str, ...]:
    return tuple(
        sorted(
            (agent_id for agent_id, score in scores.items() if score > 0),
            key=lambda agent_id: (-scores[agent_id], INTENT_TIE_BREAK_ORDER.index(agent_id)),
        )
    )


def _available_tools(agent: RegulatoryAIAgent, scope: str) -> tuple[ToolContract, ...]:
    return tuple(tool for tool in agent.tools if tool.is_available_for(scope))


def _data_classifications(tools: Iterable[ToolContract], *, restricted: bool = False) -> tuple[str, ...]:
    if restricted:
        return (DATA_RESTRICTED,)
    return tuple(sorted({tool.data_classification for tool in tools}))


def _restricted_route(*, scope: str, requested_domain: str, reason: str, scores: Mapping[str, int]) -> RegulatoryAIToolRoute:
    return RegulatoryAIToolRoute(
        status="blocked",
        supervisor=SUPERVISOR_ID,
        agent=None,
        supporting_agents=(),
        scope=scope,
        requested_domain=requested_domain,
        intent_scores=scores,
        routing_reason=reason,
        allowed_tools=(),
        data_classifications=_data_classifications((), restricted=True),
        response_constraints=(
            "Do not retrieve records or documents.",
            "Ask the user to use an approved staff account in the correct regulatory workspace.",
        ),
    )


def route_regulatory_ai_question(question: object, user: object) -> RegulatoryAIToolRoute:
    """Route a staff question to one specialist and a safe set of tool contracts.

    The result is intentionally a *plan*, not an answer.  Callers must pass it
    to an audited gateway that rechecks role, office scope, document policy,
    field redaction, freshness, and workflow state before invoking any actual
    tool.
    """

    normalized = _clean_question(question)
    scores = score_regulatory_ai_intents(normalized)
    scope = resolve_regulatory_ai_scope(user)
    requested_domain = classify_question_domain(normalized)

    if scope == SCOPE_RESTRICTED:
        return _restricted_route(
            scope=scope,
            requested_domain=requested_domain,
            scores=scores,
            reason="This account is not approved for a Regulatory AI staff tool contract.",
        )

    if requested_domain in {SCOPE_NURSING, SCOPE_MEDICAL} and scope not in {SCOPE_ALL, requested_domain}:
        return _restricted_route(
            scope=scope,
            requested_domain=requested_domain,
            scores=scores,
            reason=(
                "The question targets a different regulatory workspace. "
                "No cross-office tool contract was issued."
            ),
        )

    if len(normalized) < 3:
        return RegulatoryAIToolRoute(
            status="clarify",
            supervisor=SUPERVISOR_ID,
            agent=None,
            supporting_agents=(),
            scope=scope,
            requested_domain=requested_domain,
            intent_scores=scores,
            routing_reason="Ask a focused question about registrations, workforce, policy, data quality, compliance, or reports.",
            allowed_tools=(),
            data_classifications=(),
            response_constraints=COMMON_READ_ONLY_CONSTRAINTS,
        )

    ranked_agent_ids = _rank_intents(scores)
    # Policy/document retrieval is the safe fallback for a meaningful request
    # without a clear operational signal.  It still returns citations only from
    # the approved knowledge base.
    primary_agent_id = ranked_agent_ids[0] if ranked_agent_ids else "policy_document"
    agent = AGENT_REGISTRY[primary_agent_id]
    supporting_agents = tuple(
        AGENT_REGISTRY[agent_id]
        for agent_id in ranked_agent_ids[1:3]
        if agent_id != primary_agent_id
    )
    tools = _available_tools(agent, scope)

    response_constraints = agent.response_constraints
    if scope == SCOPE_ALL:
        response_constraints = response_constraints + (
            "Keep Nursing Council and Medical Board data separate; never combine individual records across offices.",
        )

    return RegulatoryAIToolRoute(
        status="allowed",
        supervisor=SUPERVISOR_ID,
        agent=agent,
        supporting_agents=supporting_agents,
        scope=scope,
        requested_domain=requested_domain,
        intent_scores=scores,
        routing_reason=(
            f"Routed to {agent.label} from transparent question-intent signals; "
            "only the listed read-only tool contracts may be considered."
        ),
        allowed_tools=tools,
        data_classifications=_data_classifications(tools),
        response_constraints=response_constraints,
    )


def build_regulatory_ai_tool_contract(question: object, user: object) -> dict:
    """JSON-safe convenience wrapper used by an AI gateway or API layer."""

    return route_regulatory_ai_question(question, user).as_dict()
