# Wander — Multi-Agent Travel Planner (Strands on Lambda + OpenTelemetry)

A 5-agent travel planner built with the **Strands Agents SDK** on **Amazon
Bedrock**, deployed as **AWS Lambda functions**, fronted by a **Lambda Function
URL** API and a **static webapp on S3 + CloudFront**. Both Lambdas are
instrumented with the **OpenTelemetry Lambda layer** (collector extension +
Python auto-instrumentation), whose in-process collector exports OTLP to **New
Relic**. The entire stack deploys via a **Python AWS CDK** app.

No paid third-party data APIs: web/flights/hotels use DuckDuckGo, weather uses
Open-Meteo (both free, no keys).

## Architecture

```
 Browser
   │  (HTTPS, fetch + SigV4 via Cognito unauth creds)
   ▼
CloudFront ──▶ S3 (private)         frontend/  ← static webapp, config.json injected at deploy
   │
   │  POST {prompt}
   ▼
Proxy Lambda (api/)  [Function URL, AWS_IAM]  ── OTel layer ──┐
   │  lambda:Invoke (RequestResponse), traceparent in payload │
   ▼                                                          ▼
Agent Lambda (agent/)  [Strands orchestrator] ── OTel layer ── in-process collector
   │  agents-as-tools                                         │  OTLP/HTTP (api-key)
   ├─────────────┬─────────────┬──────────────┐              ▼
   ▼             ▼             ▼              ▼          New Relic
 Search Agent  Weather Agent Flights Agent  Hotels Agent
 (DuckDuckGo)  (Open-Meteo)  (DuckDuckGo)   (DuckDuckGo)

 Telemetry: SDK auto-instrumentation → localhost collector → OTLP/HTTP → New Relic
            (traces + metrics + logs, one distributed trace across both Lambdas)
```

## Repo layout

```
agent/      Agent Lambda — Strands multi-agent app
  lambda_handler.py BedrockModel orchestrator entrypoint (handler(event, context))
  main.py           local CLI runner
  agents/           orchestrator + 4 specialists + model factory
  tools/            search / weather / flights / hotels @tool functions
  observability/    dual-mode OTel setup (layer in Lambda, in-process locally)
  requirements.txt  agent runtime deps
api/        Proxy Lambda (public Function URL) → lambda:Invoke on the agent
  lambda_function.py, requirements.txt
frontend/   Vanilla webapp (index.html, app.js, styles.css); reads /config.json
collector.yaml   OTel Collector config (OTLP → New Relic); bundled into both Lambdas
infra/      Python CDK app
  app.py            wires TravelAgent → TravelApi → TravelFrontend; reads layer ARN
  build.py          Docker-free packaging (agent/api arm64 deps + collector.yaml)
  stacks/           agent_stack.py · api_stack.py · frontend_stack.py
  cdk.json, requirements.txt
```

## Deployment outputs

After `cdk deploy`, the stack outputs the live resource values (webapp URL,
API Function URL, agent function name/ARN). Read them from your own account with:

```bash
cd infra && cdk deploy --outputs-file cdk.out/outputs.json   # outputs.json is git-ignored
# or, after deploy:
aws cloudformation describe-stacks --stack-name TravelFrontend \
  --query "Stacks[0].Outputs" --output table
```

| Resource | Where to find it |
|---|---|
| Webapp | `TravelFrontend` → `SiteURL` |
| API (Function URL) | `TravelApi` → `FunctionUrl` |
| Agent Lambda | `TravelAgent` → `AgentFunctionName` / `AgentFunctionArn` |
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
- An **opentelemetry-lambda layer ARN** for your region + architecture (see below).
- Optional: a **New Relic license/ingest key** for telemetry.

### OpenTelemetry Lambda layers

Both Lambdas attach **two** upstream
[`opentelemetry-lambda`](https://github.com/open-telemetry/opentelemetry-lambda/releases)
layers (account `184161586896`):

1. **Python layer** (`OTEL_LAMBDA_LAYER_ARN`, default `opentelemetry-python-0_20_0`)
   — the SDK, auto-instrumentation, and the `/opt/otel-instrument` exec wrapper.
   Published as a single ARN with **no arch suffix**.
2. **Collector layer** (`OTEL_COLLECTOR_LAYER_ARN`, default
   `opentelemetry-collector-<amd64|arm64>-0_22_0`) — the in-process OTel Collector
   extension that listens on `localhost:4318`. This is **architecture-specific**
   (`amd64` for x86_64, `arm64` for arm64) and must match `LAMBDA_ARCH`.

> The Python layer does **not** bundle a collector — without the collector layer,
> the SDK exports to `localhost:4318` and gets connection-refused.

The collector is configured by the bundled [`collector.yaml`](collector.yaml),
which exports OTLP/HTTP to New Relic using `NEW_RELIC_OTLP_ENDPOINT` + the
`api-key: NEW_RELIC_LICENSE_KEY` header (`decouple` processor so the handler
returns without blocking on export). Default arch is **x86_64** (the layer/wheels
match); both functions and `infra/build.py`'s vendored wheels follow `LAMBDA_ARCH`.

## Deploy (Python CDK)

```bash
cd infra
python3.12 -m venv .venv && .venv/bin/pip install -r requirements.txt
npm install aws-cdk            # local CDK CLI matching aws-cdk-lib

export AWS_PROFILE=jones-devrel AWS_REGION=us-east-1
# config read at synth (e.g. from ../.env):
export BEDROCK_MODEL_ID=us.amazon.nova-pro-v1:0
export NEW_RELIC_LICENSE_KEY=...        # optional
export NEW_RELIC_OTLP_ENDPOINT=https://otlp.nr-data.net
export LAMBDA_ARCH=x86_64
# OTel layer ARNs (defaults in infra/app.py; override per region/version):
export OTEL_LAMBDA_LAYER_ARN=arn:aws:lambda:us-east-1:184161586896:layer:opentelemetry-python-0_20_0:1
export OTEL_COLLECTOR_LAYER_ARN=arn:aws:lambda:us-east-1:184161586896:layer:opentelemetry-collector-amd64-0_22_0:1

# optional: namespace stacks alongside an existing deployment (TravelAgentV2, …)
# export STACK_SUFFIX=V2

# one-time per account/region:
PATH=".venv/bin:$PATH" npx cdk bootstrap

PATH=".venv/bin:$PATH" npx cdk deploy --all --require-approval never \
  --outputs-file cdk.out/outputs.json
```

CDK builds the agent artifact (source + linux/arm64 wheels + `collector.yaml`)
and the proxy bundle (boto3 + `collector.yaml`) with no Docker, then creates
three stacks:

- **TravelAgent** → arm64 Lambda (Strands orchestrator) + OTel layer, granted
  `bedrock:InvokeModel*`
- **TravelApi** → proxy Lambda + public Function URL (CORS) + OTel layer, granted
  `lambda:InvokeFunction` on the agent
- **TravelFrontend** → private S3 + CloudFront (OAC); deploys `frontend/` and
  injects `config.json = {"apiUrl": <Function URL>, ...}`

Outputs (CloudFront URL, Function URL, agent function name/ARN) are written to
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

Locally there is no Lambda layer, so `observability/telemetry.py` falls back to
in-process OTLP exporters pointed straight at New Relic (using
`OTEL_EXPORTER_OTLP_ENDPOINT` + `NEW_RELIC_LICENSE_KEY`).

## Models

Swap models with **no code change** via `BEDROCK_MODEL_ID` (Strands' `BedrockModel`
is provider-agnostic). Verified tool-calling on this app in us-east-1:
Amazon Nova (`us.amazon.nova-pro-v1:0`, `…nova-lite…`, `…nova-micro…`),
OpenAI GPT-OSS (`openai.gpt-oss-120b-1:0`, `…-20b-1:0`), and Anthropic
(`us.anthropic.claude-sonnet-4-6`, once model access + payment are enabled).

## Observability (New Relic)

On Lambda, the **opentelemetry-lambda layer** owns telemetry: the exec wrapper
auto-instruments the handler, boto3, httpx, and logging, and Strands attaches its
GenAI spans to the layer's global tracer provider. The in-process collector
(configured by `collector.yaml`) batches and forwards traces + metrics + logs to
New Relic over OTLP/HTTP. The proxy injects the W3C `traceparent` into the invoke
payload, so the proxy and agent appear as **one distributed trace**.

In New Relic, filter by `service.name = travel-agent-lambda` (and
`travel-api-proxy`) for Distributed Tracing (orchestrator + specialist spans),
Logs, and Metrics. CloudWatch logs are always available in parallel.

**Logs.** `OTEL_PYTHON_LOGGING_AUTO_INSTRUMENTATION_ENABLED=true` bridges Python
`logging` records into OTLP logs so they reach New Relic with a **level**
(`severityText`) and the **message** body; `OTEL_PYTHON_LOG_CORRELATION=true`
stamps `trace_id`/`span_id` onto each record so logs link to their trace. Note:
with `gen_ai_latest_experimental` on, GenAI prompt/completion/tool-call **events**
are also emitted as log records — these intentionally have no level and a
structured body (they power the AI-monitoring views), so a level-less log in New
Relic is expected and is not the application log.

**Trace completeness.** The collector pipeline omits the `decouple` processor on
purpose: `decouple` defers export to a later invocation, but under sparse traffic
the environment freezes first and the last-ending spans (parents) are lost,
making child spans show "missing parent". Synchronous export keeps traces whole.

## Teardown

```bash
cd infra && PATH=".venv/bin:$PATH" npx cdk destroy --all
```

## Notes & caveats

- Flights/hotels are **indicative** web-search summaries, not live bookings.
- The agent's internal imports are package-relative; the CDK asset zips the
  **contents** of `agent/` (entrypoint `lambda_handler.handler`), so no import
  changes are needed.
- Lambda does not pip-install at boot, so `infra/build.py` vendors linux/arm64
  wheels into each code zip and copies `collector.yaml` to the bundle root
  (`/var/task/collector.yaml`, referenced by `OPENTELEMETRY_COLLECTOR_CONFIG_URI`).
- The agent bundle also ships the OTel SDK for local dev; on `/var/task` it
  shadows the layer's copy. If versions ever conflict, pin the bundle's
  `opentelemetry-*` to match the layer release (or drop them from the agent
  bundle and use a separate dev-requirements file for local runs).
- The OTel layer ARN is region/arch-specific and supplied via
  `OTEL_LAMBDA_LAYER_ARN` — verify the current release before deploying.
- Behind a TLS-intercepting corporate proxy, local tooling needs the proxy CA:
  set `NODE_EXTRA_CA_CERTS` / `SSL_CERT_FILE` / `PIP_CERT`. Deployed AWS
  resources are unaffected.
- Secrets: the New Relic key is passed as a Lambda env var (visible in the CFN
  template). For production, source it from Secrets Manager / SSM instead.
