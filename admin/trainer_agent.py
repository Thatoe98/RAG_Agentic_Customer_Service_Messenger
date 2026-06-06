"""Trainer chat agent — the admin-facing assistant.

Lets the business owner tune the customer bot conversationally: it can search
the knowledge base (to verify what the customer bot would find) and create /
edit / delete behavior guidelines that are injected into the customer bot's
system prompt.
"""
import asyncio
import logging
from pathlib import Path

from google import genai
from google.genai import types

import guidelines
import rag
import usage_log
from config import GEMINI_API_KEY, GEMINI_MODEL

log = logging.getLogger(__name__)

_client = genai.Client(api_key=GEMINI_API_KEY)
_TRAINER_PROMPT = Path("prompts/trainer_prompt.txt").read_text(encoding="utf-8")

_TOOLS = types.Tool(
    function_declarations=[
        types.FunctionDeclaration(
            name="search_knowledge",
            description=(
                "Search the customer bot's knowledge base exactly as the customer bot would. "
                "Use this to verify what information is (or isn't) available for a topic."
            ),
            parameters={
                "type": "object",
                "properties": {"query": {"type": "string", "description": "What to look up"}},
                "required": ["query"],
            },
        ),
        types.FunctionDeclaration(
            name="list_guidelines",
            description="List all active behavior guidelines currently shaping the customer bot.",
            parameters={"type": "object", "properties": {}},
        ),
        types.FunctionDeclaration(
            name="save_guideline",
            description=(
                "Add a new behavior guideline for the customer bot (e.g. tone, strategy, a fact "
                "to always mention). Keep each guideline a single clear instruction."
            ),
            parameters={
                "type": "object",
                "properties": {"text": {"type": "string", "description": "The guideline instruction"}},
                "required": ["text"],
            },
        ),
        types.FunctionDeclaration(
            name="update_guideline",
            description="Edit the text of an existing guideline by its id.",
            parameters={
                "type": "object",
                "properties": {
                    "id": {"type": "integer", "description": "Guideline id"},
                    "text": {"type": "string", "description": "New guideline text"},
                },
                "required": ["id", "text"],
            },
        ),
        types.FunctionDeclaration(
            name="delete_guideline",
            description="Remove a guideline by its id.",
            parameters={
                "type": "object",
                "properties": {"id": {"type": "integer", "description": "Guideline id"}},
                "required": ["id"],
            },
        ),
    ]
)

_GEN_CONFIG = types.GenerateContentConfig(
    system_instruction=_TRAINER_PROMPT,
    tools=[_TOOLS],
)


async def chat(history: list[dict], user_text: str) -> str:
    """Run one trainer turn. `history` is a list of {role, content} dicts."""
    contents = [
        types.Content(
            role="model" if m["role"] == "assistant" else "user",
            parts=[types.Part(text=m["content"])],
        )
        for m in history
    ]
    contents.append(types.Content(role="user", parts=[types.Part(text=user_text)]))

    for _ in range(10):  # safety cap on tool-call iterations
        response = await _client.aio.models.generate_content(
            model=GEMINI_MODEL, contents=contents, config=_GEN_CONFIG
        )
        usage_log.log_response(response, source="trainer", model=GEMINI_MODEL)
        parts = response.candidates[0].content.parts
        function_calls = [p for p in parts if p.function_call is not None]

        if not function_calls:
            return "".join(p.text for p in parts if getattr(p, "text", None))

        response_parts = []
        for part in function_calls:
            fc = part.function_call
            log.info("Trainer tool call: %s(%s)", fc.name, dict(fc.args))
            result = await asyncio.to_thread(_execute_tool, fc.name, dict(fc.args))
            response_parts.append(
                types.Part(
                    function_response=types.FunctionResponse(
                        name=fc.name, response={"result": result}
                    )
                )
            )

        contents += [
            types.Content(role="model", parts=parts),
            types.Content(role="user", parts=response_parts),
        ]

    return "Sorry, I got stuck processing that. Please try rephrasing."


def _execute_tool(name: str, args: dict) -> str:
    if name == "search_knowledge":
        hits = rag.search(args["query"], k=5)
        if not hits:
            return "No matching content in the knowledge base."
        return "\n\n".join(
            f"[{h['source']} · score {h['score']:.2f}]\n{h['text']}" for h in hits
        )

    if name == "list_guidelines":
        items = guidelines.list_guidelines()
        if not items:
            return "No guidelines set yet."
        return "\n".join(f"#{g['id']}: {g['text']}" for g in items)

    if name == "save_guideline":
        gid = guidelines.add_guideline(args["text"])
        return f"Saved guideline #{gid}."

    if name == "update_guideline":
        ok = guidelines.update_guideline(int(args["id"]), args["text"])
        return "Updated." if ok else "No guideline with that id."

    if name == "delete_guideline":
        ok = guidelines.delete_guideline(int(args["id"]))
        return "Deleted." if ok else "No guideline with that id."

    return f"Unknown tool: {name}"
