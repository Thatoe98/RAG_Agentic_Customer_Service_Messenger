import asyncio
import logging

from google import genai
from google.genai import types

import conversations as convdb
import rag
import store
import usage_log
from config import GEMINI_API_KEY, GEMINI_MODEL
from guidelines import compose_system_prompt
from messenger import get_user_profile
from tools.handover import forward_customer_message, notify_supervisor

log = logging.getLogger(__name__)

_client = genai.Client(api_key=GEMINI_API_KEY)

_SEARCH_DECL = types.FunctionDeclaration(
    name="search_knowledge",
    description=(
        "Search uploaded company documents for specific facts: tuition, intake dates, "
        "program availability, required documents, campus details, or university policies. "
        "Only call this for document-dependent questions, not general ones."
    ),
    parameters={
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "A natural-language description of what to look up",
            }
        },
        "required": ["query"],
    },
)

_ESCALATE_DECL = types.FunctionDeclaration(
    name="escalate_to_human",
    description=(
        "Hand the conversation over to a human supervisor. Use when the customer "
        "asks for a human, the issue is complex or sensitive, the customer is "
        "frustrated, or you cannot resolve the matter."
    ),
    parameters={
        "type": "object",
        "properties": {
            "reason": {
                "type": "string",
                "description": "Short reason for escalation shown to the supervisor",
            }
        },
        "required": ["reason"],
    },
)

_TOOLS_WITH_SEARCH = types.Tool(function_declarations=[_SEARCH_DECL, _ESCALATE_DECL])
_TOOLS_ESCALATE_ONLY = types.Tool(function_declarations=[_ESCALATE_DECL])

def _gen_config() -> types.GenerateContentConfig:
    # Only offer search_knowledge when documents are actually in the knowledge base.
    # With an empty KB the model would call it, get nothing, and waste a loop iteration.
    has_docs = bool(rag.list_documents())
    return types.GenerateContentConfig(
        system_instruction=compose_system_prompt(),
        tools=[_TOOLS_WITH_SEARCH if has_docs else _TOOLS_ESCALATE_ONLY],
    )


async def handle_message(psid: str, user_text: str) -> str | None:
    """
    Process an incoming Messenger message.
    Returns the reply text, or None if the thread is escalated (bot stays silent).
    """
    if store.is_escalated(psid):
        conv = store.get_or_create(psid)
        user_profile = await get_user_profile(psid)
        user_name = _display_name(user_profile, psid)
        store.add_message(psid, "user", user_text)
        fwd_id = await forward_customer_message(
            user_name, user_text, conv.escalation_msg_id
        )
        store.register_telegram_msg(psid, fwd_id)
        return None

    store.add_message(psid, "user", user_text)
    contents = _build_contents(store.get_messages(psid))
    cfg = _gen_config()

    # Force escalation if customer explicitly asks for a human — don't trust the model for this
    if _customer_wants_human(user_text):
        log.info("Customer %s explicitly requested a human — forcing escalation", psid)
        await _execute_tool(psid, "escalate_to_human", {"reason": "Customer explicitly requested to speak with a human"})
        ack_contents = contents + [
            types.Content(role="model", parts=[types.Part(function_call=types.FunctionCall(name="escalate_to_human", args={"reason": "Customer explicitly requested to speak with a human"}))]),
            types.Content(role="user", parts=[types.Part(function_response=types.FunctionResponse(name="escalate_to_human", response={"result": "Supervisor has been notified via Telegram."}))]),
        ]
        ack = await _client.aio.models.generate_content(model=GEMINI_MODEL, contents=ack_contents, config=cfg)
        usage_log.log_response(ack, source="agent", model=GEMINI_MODEL, psid=psid)
        text = "".join(p.text for p in ack.candidates[0].content.parts if getattr(p, "text", None))
        store.add_message(psid, "assistant", text)
        return text

    for _ in range(10):  # safety cap on tool-call iterations
        response = await _client.aio.models.generate_content(
            model=GEMINI_MODEL,
            contents=contents,
            config=cfg,
        )
        usage_log.log_response(response, source="agent", model=GEMINI_MODEL, psid=psid)

        parts = response.candidates[0].content.parts
        function_calls = [p for p in parts if p.function_call is not None]

        if not function_calls:
            text = "".join(p.text for p in parts if getattr(p, "text", None))
            log.info("Gemini text reply for %s: %s", psid, text[:120])
            # Safety net: if Gemini wrote an escalation message without calling the tool, force it
            if not store.is_escalated(psid) and _looks_like_escalation(text):
                log.warning("Gemini skipped escalate_to_human tool — forcing escalation for %s", psid)
                await _execute_tool(psid, "escalate_to_human", {"reason": "customer requested human assistance"})
            store.add_message(psid, "assistant", text)
            return text

        # Execute each function call and collect responses
        response_parts = []
        for part in function_calls:
            fc = part.function_call
            log.info("Gemini tool call: %s(%s)", fc.name, dict(fc.args))
            result = await _execute_tool(psid, fc.name, dict(fc.args))
            response_parts.append(
                types.Part(
                    function_response=types.FunctionResponse(
                        name=fc.name,
                        response={"result": result},
                    )
                )
            )

        # Extend the conversation with the model turn + tool results
        contents = contents + [
            types.Content(role="model", parts=parts),
            types.Content(role="user", parts=response_parts),
        ]

    return "I'm sorry, something went wrong. Please try again."


async def _execute_tool(psid: str, name: str, args: dict) -> str:
    if name == "search_knowledge":
        return await asyncio.to_thread(rag.search_as_context, args["query"])

    if name == "escalate_to_human":
        reason = args["reason"]
        user_profile = await get_user_profile(psid)
        user_name = _display_name(user_profile, psid)
        log.info("Escalating %s to Telegram. Reason: %s", psid, reason)
        summary = _format_for_supervisor(store.get_messages(psid))
        try:
            tg_msg_id = await notify_supervisor(
                psid=psid,
                user_name=user_name,
                summary=summary,
                reason=reason,
            )
        except Exception:
            log.exception("Failed to send Telegram notification for %s", psid)
            return "Failed to notify supervisor — Telegram error."
        store.set_escalated(psid, tg_msg_id)
        convdb.set_bot_enabled(psid, False)
        log.info("Escalation complete. Telegram msg_id=%s", tg_msg_id)
        return "Supervisor has been notified via Telegram."

    return f"Unknown tool: {name}"


def _format_for_supervisor(messages: list[dict]) -> str:
    """Last 8 messages formatted as a short transcript for the Telegram notice."""
    lines = []
    for m in messages[-8:]:
        prefix = "👤" if m["role"] == "user" else "🤖"
        lines.append(f"{prefix} {m['content']}")
    return "\n".join(lines)


_HISTORY_CAP = 20  # messages sent to the model per request

def _build_contents(messages: list[dict]) -> list[types.Content]:
    contents = []
    for m in messages[-_HISTORY_CAP:]:
        role = "model" if m["role"] == "assistant" else "user"
        contents.append(
            types.Content(role=role, parts=[types.Part(text=m["content"])])
        )
    return contents


_HUMAN_REQUEST_PHRASES = [
    "speak with human",
    "speak to human",
    "talk to human",
    "talk to a human",
    "talk to person",
    "speak with a person",
    "want human",
    "need human",
    "human agent",
    "real person",
    "live agent",
    "live support",
    "connect me to",
    "transfer me",
    "human support",
    "want to speak",
    "want to talk",
]


def _customer_wants_human(text: str) -> bool:
    lower = text.lower()
    return any(phrase in lower for phrase in _HUMAN_REQUEST_PHRASES)


_ESCALATION_PHRASES = [
    "connecting you with a human",
    "connecting you to a human",
    "transferring you to",
    "transfer you to a human",
    "human agent",
    "live agent",
]


def _looks_like_escalation(text: str) -> bool:
    lower = text.lower()
    return any(phrase in lower for phrase in _ESCALATION_PHRASES)


def _display_name(profile: dict, fallback: str) -> str:
    name = f"{profile.get('first_name', '')} {profile.get('last_name', '')}".strip()
    return name or fallback
