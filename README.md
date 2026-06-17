# Wander — Multi-Agent Travel Planner (AgentCore + Strands + New Relic)

A 5-agent travel planner built with the **Strands Agents SDK** on **Amazon
Bedrock**, hosted on **Bedrock AgentCore Runtime**, fronted by a **Lambda
Function URL** API and a **static webapp on S3 + CloudFront**, monitored with
the **New Relic Python agent** (AI Monitoring) on the runtime and the **New
Relic Lambda layer** on the API. The entire stack deploys via a **Python AWS
CDK** app.

No paid third-party data APIs: web/flights/hotels use DuckDuckGo, weather uses
Open-Meteo (both free, no keys).

## Architecture

```
 Browser
   │  (HTTPS, fetch)
   ▼
CloudFront ──▶ S3 (private)         frontend/  ← static webapp, config.json injected at deploy
   │
   │  POST {prompt}
   ▼
Lambda Function URL (api/) ──SigV4──▶ AgentCore Runtime (agent/)
                                          │  Strands orchestrator (agents-as-tools)
                            ┌─────────────┼─────────────┬──────────────┐
                            ▼             ▼             ▼              ▼
                       Search Agent  Weather Agent  Flights Agent  Hotels Agent
                       (DuckDuckGo)  (Open-Meteo)   (DuckDuckGo)   (DuckDuckGo)

 Monitoring: New Relic Python agent (AgentCore, AI Monitoring) + New Relic Lambda layer (API)
```

## Repo layout

```
agent/      AgentCore agent — Strands multi-agent app
  app.py            BedrockAgentCoreApp entrypoint (POST /invocations, GET /ping)
  main.py           local CLI runner
  agents/           orchestrator + 4 specialists + model factory
  tools/            search / weather / flights / hotels @tool functions
  observability/    New Relic agent init (APM + AI Monitoring)
  requirements.txt  agent runtime deps
  Dockerfile        reference only (CDK uses direct code deploy, no container)
api/        Lambda proxy (public Function URL) → InvokeAgentRuntime
  lambda_function.py, requirements.txt
frontend/   Vanilla webapp (index.html, app.js, styles.css); reads /config.json
infra/      Python CDK app
  app.py            wires TravelAgent → TravelApi → TravelFrontend
  build.py          Docker-free packaging (agent arm64 deps, api boto3)
  stacks/           agent_stack.py · api_stack.py · frontend_stack.py
  cdk.json, requirements.txt
```

## Deployment outputs

After `cdk deploy`, the stack outputs the live resource values (webapp URL,
API Function URL, AgentCore Runtime ARN). Read them from your own account with:

Stack names are namespaced by `DEPLOYMENT_ID` (from `.env`), e.g. with
`DEPLOYMENT_ID=dev` the stacks are `TravelAgent-dev` / `TravelApi-dev` /
`TravelFrontend-dev`.

```bash
cd infra && cdk deploy --outputs-file cdk.out/outputs.json   # outputs.json is git-ignored
# or, after deploy (substitute your DEPLOYMENT_ID):
aws cloudformation describe-stacks --stack-name TravelFrontend-dev \
  --query "Stacks[0].Outputs" --output table
```

| Resource | Where to find it |
|---|---|
| Webapp | `TravelFrontend-<id>` → `SiteURL` |
| API (Function URL) | `TravelApi-<id>` → `FunctionUrl` |
| AgentCore Runtime | `TravelAgent-<id>` → `RuntimeArn` |
| Model | `us.amazon.nova-pro-v1:0` |

> ⚠️ The Function URL and webapp are **public and unauthenticated**, and every
> call triggers paid Bedrock usage. Treat the deployed URLs as secrets; add an
> API-key check in `api/lambda_function.py` or a Cognito/JWT authorizer before
> sharing broadly. Do not commit concrete account IDs, URLs, or ARNs to the repo.

## Prerequisites

- Python 3.12, Node 20/22/24 (CDK CLI), AWS credentials (`aws sts get-caller-identity`)
- **Bedrock model access + a valid AWS payment method** for the chosen model.
  Nova models are Amazon-native (no Marketplace subscription); Anthropic/OpenAI
  models need a valid payment instrument or invocation returns `AccessDeniedException`.
- Optional: a **New Relic license/ingest key** for telemetry.

## Deploy (Python CDK)

```bash
cd infra
python3.12 -m venv .venv && .venv/bin/pip install -r requirements.txt
npm install aws-cdk            # local CDK CLI matching aws-cdk-lib

export AWS_PROFILE=jones-devrel AWS_REGION=us-east-1
# All Bedrock + New Relic config lives in the repo-root .env (loaded at synth):
cp ../.env.example ../.env   # then edit ../.env (license key, account id, etc.)
# Shell-exported vars still override .env if you prefer, e.g.:
# export NEW_RELIC_LICENSE_KEY=...

# one-time per account/region:
PATH=".venv/bin:$PATH" npx cdk bootstrap

PATH=".venv/bin:$PATH" npx cdk deploy --all --require-approval never \
  --outputs-file cdk.out/outputs.json
```

CDK builds the agent artifact (source + linux/arm64 wheels) and the Lambda
bundle (boto3) with no Docker, then creates three stacks:

- **TravelAgent-<id>** → `AWS::BedrockAgentCore::Runtime` (CodeConfiguration, PYTHON_3_12)
- **TravelApi-<id>** → Lambda + public Function URL (CORS), granted `InvokeAgentRuntime`
- **TravelFrontend-<id>** → private S3 + CloudFront (OAC); deploys `frontend/` and
  injects `config.json = {"apiUrl": <Function URL>}`

Outputs (CloudFront URL, Function URL, runtime ARN) are written to
`cdk.out/outputs.json`.

### Call the API directly

```bash
curl -sS -X POST '<FunctionUrl>' -H 'Content-Type: application/json' \
  -d '{"prompt":"Plan a 2-day trip to Rome from London"}'
# → {"session_id":"...","result":"...markdown itinerary..."}
```

## Local development (agent)

```bash
cd agent
python3.12 -m venv .venv && .venv/bin/pip install -r requirements.txt
cp ../.env.example ../.env   # set NEW_RELIC_LICENSE_KEY, BEDROCK_MODEL_ID, etc.
.venv/bin/python main.py "Plan a long weekend in Lisbon from London"
```

## Models

Swap models with **no code change** via `BEDROCK_MODEL_ID` (Strands' `BedrockModel`
is provider-agnostic). Verified tool-calling on this app in us-east-1:
Amazon Nova (`us.amazon.nova-pro-v1:0`, `…nova-lite…`, `…nova-micro…`),
OpenAI GPT-OSS (`openai.gpt-oss-120b-1:0`, `…-20b-1:0`), and Anthropic
(`us.anthropic.claude-sonnet-4-6`, once model access + payment are enabled).

## Observability (New Relic)

**AgentCore runtime** — the **New Relic Python agent** is initialized in
`agent/observability/telemetry.py` and reports when `NEW_RELIC_LICENSE_KEY` is
set on the runtime. With `NEW_RELIC_AI_MONITORING_ENABLED=true`, the agent's
native instrumentation captures the Bedrock (`botocore`) / OpenAI calls Strands
makes as **AI Monitoring** LLM events (model, tokens, latency) alongside APM
transactions and forwarded logs. Find it in New Relic as APM app
`travel-agent-agentcore`; session/environment are attached as custom attributes.

**API Lambda** — the **New Relic Lambda layer** (`NewRelicPython312`) wraps the
proxy handler; its bundled extension sends data directly to New Relic using
`NEW_RELIC_LICENSE_KEY` + `NEW_RELIC_ACCOUNT_ID` (no CloudWatch forwarding).
Distributed tracing links the Lambda to the runtime.

AgentCore also ships built-in CloudWatch GenAI observability in parallel.

## Teardown

```bash
cd infra && PATH=".venv/bin:$PATH" npx cdk destroy --all
```

## Notes & caveats

- Flights/hotels are **indicative** web-search summaries, not live bookings.
- The agent's internal imports are package-relative; the CDK asset zips the
  **contents** of `agent/` (entrypoint `app.py`), so no import changes are needed.
- The AgentCore managed runtime does not pip-install at boot, so `infra/build.py`
  vendors linux/arm64 wheels into the code zip.
- Behind a TLS-intercepting corporate proxy, local tooling needs the proxy CA:
  set `NODE_EXTRA_CA_CERTS` / `SSL_CERT_FILE` / `PIP_CERT`. Deployed AWS
  resources are unaffected.
- Secrets: the New Relic key is passed as a runtime env var (visible in the CFN
  template). For production, source it from Secrets Manager / SSM instead.
