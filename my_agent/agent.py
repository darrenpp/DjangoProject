import os

from google.adk.agents import Agent


DEFAULT_MODEL = (
    os.environ.get("AI_GOOGLE_ADK_MODEL")
    or os.environ.get("GOOGLE_ADK_MODEL")
    or "gemini-flash-latest"
)


def staff_ai_integration_status() -> dict:
    """Return how this ADK agent is expected to connect to the Django Staff AI."""
    return {
        "project": "PNG Regulatory Bodies Online Platform",
        "django_staff_ai_routes": [
            "/dashboard/staff-ai/",
            "/dashboard/staff-ai/chat/",
            "/dashboard/staff-ai/chat/stream/",
        ],
        "database_access": (
            "Live registry lookups are exposed through the Django-integrated ADK provider "
            "with role-scoped read-only ORM tools. The standalone CLI agent does not bypass "
            "Django login, staff scope, or board-governance boundaries."
        ),
        "safety": [
            "No raw SQL.",
            "No write operations.",
            "No approval or licence issuance.",
            "No DOB, contact details, full addresses, raw payloads, or payment amounts.",
        ],
    }


root_agent = Agent(
    name="my_agent",
    model=DEFAULT_MODEL,
    description="Standalone ADK smoke-test agent for the NDOH regulatory Staff AI integration.",
    instruction=(
        "You are a concise smoke-test agent for the PNG Regulatory Bodies Online Platform. "
        "Explain how the Django Staff AI integration works, and use the provided tool when "
        "asked about database access or safety boundaries. Do not claim to read live records "
        "from the standalone CLI; live record access is only available through authenticated "
        "Django Staff AI requests."
    ),
    tools=[staff_ai_integration_status],
)
