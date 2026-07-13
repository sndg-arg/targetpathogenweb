"""Manual smoke test for the provider-agnostic LLM agent loop.

Usage:
    python manage.py test_llm_agent "What time is it right now?"

Requires credentials for whichever provider TPW_LLM_PROVIDER selects
(ANTHROPIC_API_KEY for the default "anthropic" provider) to be set in the
environment.
"""
from django.core.management.base import BaseCommand

from tpweb.services.llm.agent import Agent
from tpweb.services.llm.provider_factory import get_provider
from tpweb.services.llm.tools.demo import ENTRY as GET_CURRENT_TIME_ENTRY


class Command(BaseCommand):
    help = "Smoke-test the provider-agnostic LLM agent loop with a trivial tool."

    def add_arguments(self, parser):
        parser.add_argument("prompt", nargs="?", default="What time is it right now?")

    def handle(self, *args, **options):
        provider = get_provider()
        agent = Agent(
            provider=provider,
            tools={"get_current_time": GET_CURRENT_TIME_ENTRY},
            system="You are a minimal test agent. Use tools when they help answer the question.",
        )
        answer = agent.run(options["prompt"])
        self.stdout.write(answer)
