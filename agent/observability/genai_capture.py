"""Make the ``OTEL_INSTRUMENTATION_GENAI_CAPTURE_*`` env vars real controls.

Strands emits GenAI telemetry through its own tracer (``strands.telemetry``),
which captures message content and tool input/output *unconditionally* — it
does not consult the ``OTEL_INSTRUMENTATION_GENAI_CAPTURE_*`` variables that the
upstream OpenTelemetry GenAI instrumentations use. This module bridges that gap:
it subclasses the Strands tracer and gates content capture on those variables,
then installs the gated tracer as the global singleton.

All four flags default to ``true`` (capture everything — Strands' native
behaviour). Set any to a falsey value (``false``/``0``/``no``/``off``) to redact
the corresponding data before it is ever written to a span.

Flag → what it controls (as mapped onto Strands' span events):

  OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT
      Chat prompt/completion text and system instructions
      (``gen_ai.input.messages`` / ``gen_ai.output.messages`` /
      ``gen_ai.system_instructions`` on ``chat`` spans, plus the legacy
      ``content``/``message`` event attributes).

  OTEL_INSTRUMENTATION_GENAI_CAPTURE_TOOL_INPUT
      Tool-call arguments (``gen_ai.input.messages`` on ``execute_tool`` spans).

  OTEL_INSTRUMENTATION_GENAI_CAPTURE_TOOL_OUTPUT
      Tool results (``gen_ai.output.messages`` on ``execute_tool`` spans).

  OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_METADATA
      Supplementary model/response metadata Strands attaches as span
      attributes: cache token counts and server timing
      (``gen_ai.usage.cache_*``, ``gen_ai.server.time_to_first_token``).
      Core token counts and the model id are always kept. Strands bakes
      per-message role/finish_reason into the serialized message payload, so
      those follow MESSAGE_CONTENT rather than this flag.

Gating happens at the source: when a flag is off the data never enters the span,
so nothing sensitive is buffered or exported. Telemetry failures are swallowed —
this must never break the agent.

Strands writes the captured content into OTLP span *events*. New Relic (and some
other OTLP backends) don't expose span events to NRQL, so by default this module
also mirrors the surviving content onto span *attributes* (the same mechanism
Strands uses for its Langfuse path). Disable with
``OTEL_GENAI_CAPTURE_CONTENT_ON_SPAN_ATTRIBUTES=false`` if you only want events.
"""

import logging
import os

logger = logging.getLogger(__name__)

# Event-attribute keys Strands uses to carry content, by GenAI convention mode.
_MESSAGE_CONTENT_KEYS = ("gen_ai.system_instructions",)
_INPUT_MESSAGE_KEYS = ("gen_ai.input.messages",)
_OUTPUT_MESSAGE_KEYS = ("gen_ai.output.messages",)
# Legacy (v1.36) event attribute keys, gated by event name.
_LEGACY_CONTENT_KEYS = ("content", "message")

# Content keys that, when present, are also mirrored onto span *attributes* so
# backends that don't surface OTLP span events (New Relic NRQL) can query them.
_SPAN_ATTR_PROMOTE_KEYS = (
    "gen_ai.input.messages",
    "gen_ai.output.messages",
    "gen_ai.system_instructions",
    "content",
    "message",
)


def _flag(name: str, default: bool = True) -> bool:
    """Parse a boolean env var; unset ⇒ default (capture on)."""
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() not in ("false", "0", "no", "off", "")


def install_genai_capture_gate() -> bool:
    """Install a tracer that honours the ``*_CAPTURE_*`` flags.

    Must run after telemetry env vars are set and before any Strands agent is
    constructed (agents grab the tracer via ``get_tracer()`` at build time).

    Returns:
        True if the gated tracer was installed, False otherwise.
    """
    capture_message_content = _flag("OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT")
    capture_message_metadata = _flag("OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_METADATA")
    capture_tool_input = _flag("OTEL_INSTRUMENTATION_GENAI_CAPTURE_TOOL_INPUT")
    capture_tool_output = _flag("OTEL_INSTRUMENTATION_GENAI_CAPTURE_TOOL_OUTPUT")
    # Strands writes content into OTLP span *events*; New Relic (and some other
    # OTLP backends) don't surface span events for NRQL. Mirror the captured
    # content onto span *attributes* too so it's queryable there. Default on.
    content_on_span_attrs = _flag("OTEL_GENAI_CAPTURE_CONTENT_ON_SPAN_ATTRIBUTES")

    try:
        from strands.telemetry import tracer as strands_tracer_mod
    except Exception as exc:  # noqa: BLE001 - Strands not importable; skip silently
        logger.warning("Strands tracer unavailable — GenAI capture gate not installed: %s", exc)
        return False

    BaseTracer = strands_tracer_mod.Tracer

    class _GatedTracer(BaseTracer):
        """Strands tracer that drops content/metadata per the capture flags."""

        def _add_event(self, span, event_name, event_attributes, to_span_attributes=False):  # type: ignore[override]
            try:
                event_attributes = self._filter_event_attributes(span, event_name, event_attributes)
                # Promote surviving content onto span attributes for NRQL-style
                # backends that don't expose span events.
                if (
                    content_on_span_attrs
                    and event_attributes
                    and any(k in event_attributes for k in _SPAN_ATTR_PROMOTE_KEYS)
                ):
                    to_span_attributes = True
            except Exception as exc:  # noqa: BLE001 - never let redaction break tracing
                logger.debug("GenAI capture gate: event filter error: %s", exc)
            return super()._add_event(span, event_name, event_attributes, to_span_attributes)

        def _add_optional_usage_and_metrics_attributes(self, attributes, usage, metrics):  # type: ignore[override]
            if not capture_message_metadata:
                return  # skip cache-token + server-timing metadata
            return super()._add_optional_usage_and_metrics_attributes(attributes, usage, metrics)

        @staticmethod
        def _operation_name(span) -> str:
            attrs = getattr(span, "attributes", None) or {}
            return str(attrs.get("gen_ai.operation.name", ""))

        def _filter_event_attributes(self, span, event_name, event_attributes):
            if not event_attributes:
                return event_attributes
            # Nothing disabled ⇒ leave the payload untouched (native behaviour).
            if capture_message_content and capture_tool_input and capture_tool_output:
                return event_attributes

            is_tool = self._operation_name(span) == "execute_tool"
            filtered = dict(event_attributes)

            if is_tool:
                if not capture_tool_input:
                    for key in _INPUT_MESSAGE_KEYS:
                        filtered.pop(key, None)
                    if event_name == "gen_ai.tool.message":
                        filtered.pop("content", None)
                if not capture_tool_output:
                    for key in _OUTPUT_MESSAGE_KEYS:
                        filtered.pop(key, None)
                    if event_name == "gen_ai.choice":
                        filtered.pop("message", None)
            elif not capture_message_content:
                for key in (*_MESSAGE_CONTENT_KEYS, *_INPUT_MESSAGE_KEYS, *_OUTPUT_MESSAGE_KEYS):
                    filtered.pop(key, None)
                for key in _LEGACY_CONTENT_KEYS:
                    filtered.pop(key, None)

            return filtered

    strands_tracer_mod._tracer_instance = _GatedTracer()
    logger.info(
        "GenAI capture gate installed (message_content=%s, message_metadata=%s, "
        "tool_input=%s, tool_output=%s, content_on_span_attrs=%s).",
        capture_message_content,
        capture_message_metadata,
        capture_tool_input,
        capture_tool_output,
        content_on_span_attrs,
    )
    return True
