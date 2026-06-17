"""Local CLI runner for the travel multi-agent app.

Loads .env, initializes the New Relic agent, runs the orchestrator against a
demo (or command-line) travel query, prints the result, and flushes telemetry.

Usage:
    python main.py
    python main.py "Plan a long weekend in Lisbon in May with flights from London"
"""

import logging
import sys
import uuid

from dotenv import load_dotenv

DEMO_PROMPT = (
    "Plan a 5-day trip from NYC to Tokyo in March — find flights, hotels, "
    "and weather, and give me a day-by-day outline."
)


def main() -> int:
    load_dotenv()
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    # The New Relic agent must be set up before any LLM client is constructed.
    from observability import record_attributes, setup_telemetry, shutdown_telemetry

    setup_telemetry("travel-agent-local")

    import newrelic.agent

    from agents.orchestrator import run_travel_query

    prompt = " ".join(sys.argv[1:]).strip() or DEMO_PROMPT
    session_id = str(uuid.uuid4())
    print(f"\n=== Travel query (session {session_id}) ===\n{prompt}\n")

    try:
        with newrelic.agent.BackgroundTask(
            newrelic.agent.application(), name="travel-query"
        ):
            record_attributes({"session.id": session_id, "app.environment": "local"})
            result = run_travel_query(prompt)
        print("\n=== Travel plan ===\n")
        print(result)
        return 0
    finally:
        shutdown_telemetry()


if __name__ == "__main__":
    raise SystemExit(main())
