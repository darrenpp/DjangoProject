from types import SimpleNamespace
from unittest import TestCase

from apps.dashboard.regulatory_ai_agents import (
    AGENT_REGISTRY,
    DATA_AGGREGATE_GOVERNED,
    DATA_PUBLIC_POLICY,
    DATA_RESTRICTED,
    DATA_STAGING_ONLY,
    PROHIBITED_CAPABILITIES,
    SCOPE_ALL,
    SCOPE_MEDICAL,
    SCOPE_NURSING,
    SCOPE_RESTRICTED,
    build_regulatory_ai_tool_contract,
    classify_question_domain,
    route_regulatory_ai_question,
)


def make_user(*, role="registrar", department="Nursing Council", active=True, authenticated=True):
    return SimpleNamespace(
        is_authenticated=authenticated,
        is_active=active,
        role=role,
        department=department,
        job_title="",
        cadre_name="",
        employee_details="",
        username="agent.router.test",
        first_name="",
        last_name="",
        email="",
    )


class RegulatoryAIAgentRouterTests(TestCase):
    def setUp(self):
        self.nursing_user = make_user()
        self.medical_user = make_user(department="Medical Board")
        self.admin_user = make_user(role="admin", department="National Administration")

    def test_registry_has_each_named_regulatory_specialist(self):
        self.assertEqual(
            set(AGENT_REGISTRY),
            {
                "data_quality",
                "registration",
                "workforce_analytics",
                "policy_document",
                "compliance",
                "report",
            },
        )
        for agent in AGENT_REGISTRY.values():
            self.assertTrue(agent.tools)
            self.assertTrue(agent.response_constraints)

    def test_nursing_retirement_question_routes_to_aggregate_workforce_contract(self):
        route = route_regulatory_ai_question(
            "How many Nursing Council professionals will retire in the next ten years?",
            self.nursing_user,
        )
        contract = route.as_dict()

        self.assertEqual(route.status, "allowed")
        self.assertEqual(route.scope, SCOPE_NURSING)
        self.assertEqual(route.agent.identifier, "workforce_analytics")
        self.assertIn(DATA_AGGREGATE_GOVERNED, route.data_classifications)
        self.assertTrue(contract["requires_citations"])
        self.assertFalse(contract["direct_database_access"])
        self.assertFalse(contract["direct_llm_access"])
        self.assertIn("direct_database_access", contract["prohibited_capabilities"])
        self.assertNotIn("search_scoped_registration_records", [tool["name"] for tool in contract["allowed_tools"]])

    def test_medical_question_is_blocked_for_nursing_staff_before_any_tool_contract(self):
        route = route_regulatory_ai_question(
            "Show Medical Board specialist credential and accreditation risks.",
            self.nursing_user,
        )

        self.assertEqual(route.status, "blocked")
        self.assertEqual(route.scope, SCOPE_NURSING)
        self.assertEqual(route.requested_domain, SCOPE_MEDICAL)
        self.assertEqual(route.allowed_tools, ())
        self.assertEqual(route.data_classifications, (DATA_RESTRICTED,))
        self.assertIn("different regulatory workspace", route.routing_reason)

    def test_registration_contract_declares_bounded_scoped_record_lookup_safeguards(self):
        route = route_regulatory_ai_question(
            "Find registration RN202600123 and show its ATP renewal status.",
            self.nursing_user,
        )
        contract = route.as_dict()
        lookup = next(
            tool for tool in contract["allowed_tools"]
            if tool["name"] == "search_scoped_registration_records"
        )

        self.assertEqual(route.agent.identifier, "registration")
        self.assertTrue(lookup["read_only"])
        self.assertTrue(lookup["requires_explicit_identifier"])
        self.assertEqual(lookup["data_classification"], "role_scoped_registry")
        self.assertIn("existing office-scoped queryset", " ".join(lookup["constraints"]))
        self.assertTrue(any("redaction" in rule.lower() for rule in route.response_constraints))

    def test_data_quality_route_never_promotes_or_merges_records(self):
        route = route_regulatory_ai_question(
            "Review Excel import duplicates, missing data, and validation errors.",
            self.medical_user,
        )

        self.assertEqual(route.agent.identifier, "data_quality")
        self.assertIn(DATA_STAGING_ONLY, route.data_classifications)
        constraints = " ".join(route.response_constraints + tuple(
            constraint
            for tool in route.allowed_tools
            for constraint in tool.constraints
        ))
        self.assertIn("never promote", constraints.lower())
        self.assertIn("human review", constraints.lower())
        self.assertTrue(route.requires_human_approval)

    def test_policy_route_requires_authoritative_sources(self):
        route = route_regulatory_ai_question(
            "What are the Nursing Council overseas registration requirements? Cite the policy sources.",
            self.nursing_user,
        )

        self.assertEqual(route.agent.identifier, "policy_document")
        self.assertIn(DATA_PUBLIC_POLICY, route.data_classifications)
        self.assertTrue(route.requires_citations)
        self.assertTrue(all(tool.citations_required for tool in route.allowed_tools))

    def test_compliance_agent_exposes_only_aggregate_not_case_records(self):
        route = route_regulatory_ai_question(
            "Show Medical Board accreditation, CPD, credential, and compliance risk trends.",
            self.medical_user,
        )
        tool_names = {tool.name for tool in route.allowed_tools}
        tool_constraints = " ".join(
            constraint for tool in route.allowed_tools for constraint in tool.constraints
        ).lower()

        self.assertEqual(route.agent.identifier, "compliance")
        self.assertEqual(route.scope, SCOPE_MEDICAL)
        self.assertEqual(route.data_classifications, (DATA_AGGREGATE_GOVERNED,))
        self.assertNotIn("get_disciplinary_case", tool_names)
        self.assertNotIn("get_complaint_case", tool_names)
        self.assertIn("do not expose complaint narratives", tool_constraints)

    def test_report_contract_requires_human_approval_and_sources(self):
        route = route_regulatory_ai_question(
            "Prepare a board briefing report for the next meeting.",
            self.medical_user,
        )

        self.assertEqual(route.agent.identifier, "report")
        self.assertTrue(route.requires_citations)
        self.assertTrue(route.requires_human_approval)
        self.assertTrue(any("draft" in rule.lower() for rule in route.response_constraints))

    def test_admin_can_compare_aggregates_but_contract_requires_office_separation(self):
        route = route_regulatory_ai_question(
            "Compare Nursing workforce retirement with Medical Board specialist distribution.",
            self.admin_user,
        )

        self.assertEqual(route.status, "allowed")
        self.assertEqual(route.scope, SCOPE_ALL)
        self.assertEqual(route.requested_domain, SCOPE_ALL)
        self.assertEqual(route.agent.identifier, "workforce_analytics")
        self.assertTrue(any("remain separate" in rule.lower() or "keep nursing" in rule.lower()
                            for rule in route.response_constraints))
        self.assertIn(DATA_AGGREGATE_GOVERNED, route.data_classifications)

    def test_non_staff_or_inactive_user_receives_no_contract(self):
        route = route_regulatory_ai_question(
            "Show workforce shortages by province.",
            make_user(role="nurse", department="", active=True),
        )

        self.assertEqual(route.status, "blocked")
        self.assertEqual(route.scope, SCOPE_RESTRICTED)
        self.assertEqual(route.allowed_tools, ())

    def test_json_wrapper_is_contract_only_and_not_an_executable_agent(self):
        contract = build_regulatory_ai_tool_contract(
            "Explain the ATP renewal policy and cite authoritative sources.",
            self.nursing_user,
        )

        self.assertEqual(contract["execution_mode"], "contract_only")
        self.assertFalse(contract["direct_database_access"])
        self.assertFalse(contract["direct_llm_access"])
        self.assertEqual(contract["agent"]["id"], "policy_document")
        self.assertEqual(set(PROHIBITED_CAPABILITIES), set(contract["prohibited_capabilities"]))

    def test_domain_classifier_keeps_joint_questions_explicit(self):
        self.assertEqual(classify_question_domain("Nursing Council ATP"), SCOPE_NURSING)
        self.assertEqual(classify_question_domain("Medical Board specialists"), SCOPE_MEDICAL)
        self.assertEqual(
            classify_question_domain("Compare Nursing Council and Medical Board trends"),
            SCOPE_ALL,
        )
