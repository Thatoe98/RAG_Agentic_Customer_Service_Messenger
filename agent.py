import asyncio
import logging
from pathlib import Path

from google import genai
from google.genai import types

import store
from config import GEMINI_API_KEY, GEMINI_MODEL
from messenger import get_user_profile
from tools import drive
from tools.handover import forward_customer_message, notify_supervisor

log = logging.getLogger(__name__)

_client = genai.Client(api_key=GEMINI_API_KEY)
_SYSTEM_PROMPT = Path("prompts/system_prompt.txt").read_text()

_TOOLS = types.Tool(
    function_declarations=[
        types.FunctionDeclaration(
            name="search_drive",
            description=(
                "Search company Google Drive documents for product info, pricing, "
                "policies, or structured data relevant to the customer's question. "
                "Call this only when the answer is not already known."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Keywords to search for in company documents",
                    }
                },
                "required": ["query"],
            },
        ),
        types.FunctionDeclaration(
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
        ),
    ]
)

_GEN_CONFIG = types.GenerateContentConfig(
    system_instruction=_SYSTEM_PROMPT,
    tools=[_TOOLS],
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

    # Force escalation if customer explicitly asks for a human — don't trust the model for this
    if _customer_wants_human(user_text):
        log.info("Customer %s explicitly requested a human — forcing escalation", psid)
        await _execute_tool(psid, "escalate_to_human", {"reason": "Customer explicitly requested to speak with a human"})
        ack_contents = contents + [
            types.Content(role="model", parts=[types.Part(function_call=types.FunctionCall(name="escalate_to_human", args={"reason": "Customer explicitly requested to speak with a human"}))]),
            types.Content(role="user", parts=[types.Part(function_response=types.FunctionResponse(name="escalate_to_human", response={"result": "Supervisor has been notified via Telegram."}))]),
        ]
        ack = await _client.aio.models.generate_content(model=GEMINI_MODEL, contents=ack_contents, config=_GEN_CONFIG)
        text = "".join(p.text for p in ack.candidates[0].content.parts if getattr(p, "text", None))
        store.add_message(psid, "assistant", text)
        return text

    for _ in range(10):  # safety cap on tool-call iterations
        response = await _client.aio.models.generate_content(
            model=GEMINI_MODEL,
            contents=contents,
            config=_GEN_CONFIG,
        )

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
    if name == "search_drive":
        return await _drive_lookup(psid, args["query"])

    if name == "escalate_to_human":
        reason = args["reason"]
        user_profile = await get_user_profile(psid)
        user_name = _display_name(user_profile, psid)
        log.info("Escalating %s to Telegram. Reason: %s", psid, reason)
        summary = await _summarize_conversation(store.get_messages(psid))
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
        log.info("Escalation complete. Telegram msg_id=%s", tg_msg_id)
        return "Supervisor has been notified via Telegram."

    return f"Unknown tool: {name}"


async def _summarize_conversation(messages: list[dict]) -> str:
    transcript = "\n".join(
        f"{'Customer' if m['role'] == 'user' else 'Bot'}: {m['content']}"
        for m in messages
    )
    prompt = (
        "Summarize this customer support conversation in 3-5 concise English bullet points "
        "for a supervisor who is taking over. Cover: what the customer wants, key details they shared, "
        "and why this is being escalated.\n\n" + transcript
    )
    response = await _client.aio.models.generate_content(
        model=GEMINI_MODEL,
        contents=[types.Content(role="user", parts=[types.Part(text=prompt)])],
    )
    return response.candidates[0].content.parts[0].text


async def _drive_lookup(psid: str, query: str) -> str:
    cached = store.get_drive_cache(psid, query)
    if cached:
        return cached
    result = await asyncio.to_thread(drive.search_and_read, query)
    store.set_drive_cache(psid, query, result)
    return result


def _build_contents(messages: list[dict]) -> list[types.Content]:
    contents = []
    for m in messages:
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
    "connecting you with",
    "connecting you to",
    "team member",
    "human agent",
    "speak with a person",
    "speak to a person",
    "transfer you",
    "escalat",
]


def _looks_like_escalation(text: str) -> bool:
    lower = text.lower()
    return any(phrase in lower for phrase in _ESCALATION_PHRASES)


def _display_name(profile: dict, fallback: str) -> str:
    name = f"{profile.get('first_name', '')} {profile.get('last_name', '')}".strip()
    return name or fallback
