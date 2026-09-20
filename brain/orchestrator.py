import datetime
import logging
import time
import uuid
from typing import Any, Dict

from brain.config import DEBUG_STREAM
from brain.executor import executor
from brain.groq_voice import generate_friday_reply_detailed
from brain.jev_reflex import evaluate_intent_with_jev
from db.dynamic_repo import dynamic_repo
from db.session import get_db_session
from models import Envelope, MsgBody

logger = logging.getLogger("brain_orchestrator")


async def process_user_interaction(envelope: Envelope, server_instance=None) -> Envelope:
    """
    Universal metadata-driven execution pipeline:
    1. Ingest request & initialize telemetry trace.
    2. Jev System 1: Determines operation and entity in <40ms.
    3. Dynamic Repository: Executes strongly-typed ORM operations on PostgreSQL.
    4. Groq Voice: Streams charismatic Friday conversational response.
    5. Telemetry Broadcast: Streams full debug trace to connected laptop(s).
    """
    pipeline_start = time.perf_counter()
    user_text = envelope.body.get("text", "")
    if not user_text:
        return Envelope.create(
            type="msg",
            source="server:friday-agent",
            target=envelope.source,
            body=MsgBody(text="I didn't catch that, sir. Could you repeat?"),
        )

    logger.info(f"🧠 [Brain Orchestrator] Processing input from {envelope.source}: '{user_text}'")

    # Step 1: Jev System 1 Dynamic Evaluation (<40ms)
    decision = await evaluate_intent_with_jev(user_text, source_device=envelope.source)

    # Step 2: Safety Gate Check
    if decision.is_destructive:
        logger.warning(f"🚫 [Safety Gate] Blocked destructive action for input: '{user_text}'")
        friday_speech, groq_meta = await generate_friday_reply_detailed(
            user_input=user_text,
            action_summary="Action blocked because it was flagged as potentially destructive or high-risk.",
        )
        reply_env = Envelope.create(
            type="msg",
            source="server:friday-agent",
            target=envelope.source,
            body=MsgBody(text=friday_speech),
        )

        if DEBUG_STREAM and server_instance:
            trace_payload = {
                "trace_id": f"tr_{uuid.uuid4().hex[:8]}",
                "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
                "request": {"source": envelope.source, "target": envelope.target, "text": user_text, "envelope_id": envelope.id},
                "jev_system1": {
                    "operation": decision.operation,
                    "entity": decision.entity,
                    "is_destructive": decision.is_destructive,
                    "urgency": decision.urgency,
                    "latency_ms": decision.latency_ms,
                },
                "database": {"operation": "blocked", "sql_executed": "-- BLOCKED BY SAFETY GATE --", "latency_ms": 0.0},
                "groq_system2": {"model": groq_meta.get("model", "openai/gpt-oss-20b"), "speech_reply": friday_speech, "latency_ms": groq_meta.get("latency_ms", 0.0)},
                "total_pipeline_ms": round((time.perf_counter() - pipeline_start) * 1000, 2),
            }
            trace_env = Envelope.create(type="debug_trace", source="server:friday-agent", target="laptop", body=trace_payload)
            await server_instance.route_envelope(None, trace_env)

        return reply_env

    action_summary = "Processed request."
    action_data: Dict[str, Any] = {}

    # Step 3: Pure Dynamic Execution (Strategy Dispatcher - 0 if/else statements)
    try:
        async with get_db_session() as session:
            action_summary, action_data = await executor.execute(
                session=session,
                decision=decision,
                user_text=user_text,
                server_instance=server_instance,
                envelope=envelope,
            )
    except Exception as exc:
        logger.error(f"Error executing dynamic action: {exc}", exc_info=True)
        action_summary = f"Attempted operation on {decision.entity} but encountered: {exc}"

    # Step 4: Generate Friday's Voice Response via Groq (openai/gpt-oss-20b)
    friday_speech, groq_meta = await generate_friday_reply_detailed(
        user_input=user_text,
        action_summary=action_summary,
        context={
            "operation": decision.operation,
            "entity": decision.entity,
            "urgency": decision.urgency,
            "action_data": action_data,
        },
    )

    total_pipeline_ms = round((time.perf_counter() - pipeline_start) * 1000, 2)

    # Step 5: Broadcast Telemetry Debug Trace to Laptop
    if DEBUG_STREAM and server_instance:
        db_trace = dynamic_repo.get_last_trace() or {
            "entity": decision.entity,
            "operation": decision.operation,
            "sql_executed": "-- No database operation executed --",
            "sql_parameters": {},
            "latency_ms": 0.0,
            "rows_affected": 0,
            "result_summary": "No direct DB query",
        }

        trace_payload = {
            "trace_id": f"tr_{uuid.uuid4().hex[:8]}",
            "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            "request": {
                "source": envelope.source,
                "target": envelope.target,
                "text": user_text,
                "envelope_id": envelope.id,
            },
            "jev_system1": {
                "operation": decision.operation,
                "entity": decision.entity,
                "target_device": decision.target_device,
                "is_destructive": decision.is_destructive,
                "urgency": decision.urgency,
                "parameters": decision.parameters,
                "latency_ms": decision.latency_ms,
            },
            "database": db_trace,
            "groq_system2": {
                "model": groq_meta.get("model", "openai/gpt-oss-20b"),
                "speech_reply": friday_speech,
                "latency_ms": groq_meta.get("latency_ms", 0.0),
            },
            "total_pipeline_ms": total_pipeline_ms,
        }

        trace_env = Envelope.create(
            type="debug_trace",
            source="server:friday-agent",
            target="laptop",
            body=trace_payload,
        )
        logger.info(f"📊 [Telemetry] Streaming debug trace {trace_payload['trace_id']} ({total_pipeline_ms}ms) to laptop")
        await server_instance.route_envelope(None, trace_env)

    # Step 6: Package and Deliver Response Envelope
    return Envelope.create(
        type="msg",
        source="server:friday-agent",
        target=envelope.source,
        body=MsgBody(text=friday_speech),
    )
