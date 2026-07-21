import json
import logging
import os
import threading
from openai import OpenAI
from .tools import TOOLS
from .prompts import get_receptionist_prompt
from ..services.calendar import check_availability, book_appointment
from ..services.sms import send_sms
from ..services.database import log_call

logger = logging.getLogger(__name__)

MODEL = os.getenv("OPENAI_MODEL", "gpt-4o")

_client = None


def get_client():
    """Lazily create the OpenAI client so the app can boot without a key set."""
    global _client
    if _client is None:
        _client = OpenAI()  # reads OPENAI_API_KEY from the environment
    return _client


def handle_conversation_turn(conversation_history: list, caller_phone: str = None) -> dict:
    """Run the agentic loop — the model keeps calling tools until done.
    Returns {"text": str, "end_call": bool}.

    `conversation_history` is a list of OpenAI-format messages with string
    content (role: "user" | "assistant"), as prepared by views.py.
    """
    system_prompt = get_receptionist_prompt()
    if caller_phone:
        system_prompt += f"\n\nCALLER INFO:\n- The caller's phone number is {caller_phone}. Use this number for booking and SMS by default. Just confirm: \"We'll send a confirmation to the number you're calling from. Would you like it sent to a different number instead?\""

    messages = [{"role": "system", "content": system_prompt}] + list(conversation_history)

    response = get_client().chat.completions.create(
        model=MODEL,
        max_tokens=1024,
        messages=messages,
        tools=TOOLS,
        tool_choice="auto",
        parallel_tool_calls=False,
    )
    msg = response.choices[0].message

    should_end_call = False
    last_tool_name = None

    while msg.tool_calls:
        # Append the assistant turn (with its tool_calls) before the tool results.
        messages.append({
            "role": "assistant",
            "content": msg.content or "",
            "tool_calls": [
                {
                    "id": tc.id,
                    "type": "function",
                    "function": {"name": tc.function.name, "arguments": tc.function.arguments},
                }
                for tc in msg.tool_calls
            ],
        })

        # Every tool_call must get a matching tool result message.
        for tc in msg.tool_calls:
            name = tc.function.name
            try:
                args = json.loads(tc.function.arguments or "{}")
            except json.JSONDecodeError:
                args = {}

            if name == "end_call":
                logger.info(f"[END_CALL] reason={args.get('reason', 'unknown')}")
                should_end_call = True
                messages.append({
                    "role": "tool",
                    "tool_call_id": tc.id,
                    "content": json.dumps({"success": True}),
                })
                continue

            last_tool_name = name
            logger.info(f"[TOOL] {name} {json.dumps(args)}")
            try:
                tool_result = execute_tool(name, args)
            except Exception as e:
                logger.error(f"[TOOL ERROR] {name}: {e}")
                tool_result = {"error": str(e)}
            logger.info(f"[RESULT] {json.dumps(tool_result)}")
            messages.append({
                "role": "tool",
                "tool_call_id": tc.id,
                "content": json.dumps(tool_result),
            })

        if should_end_call:
            break

        response = get_client().chat.completions.create(
            model=MODEL,
            max_tokens=1024,
            messages=messages,
            tools=TOOLS,
            tool_choice="auto",
            parallel_tool_calls=False,
        )
        msg = response.choices[0].message

    response_text = (msg.content or "").strip()

    # Fallback: if the model returned empty text after tools, provide a sensible response.
    if not response_text:
        if should_end_call:
            response_text = "Thanks for calling Bright Smile Dental. Have a great day, goodbye!"
        elif last_tool_name:
            logger.warning(f"[EMPTY RESPONSE] after tool={last_tool_name}, using fallback")
            if last_tool_name in ("book_appointment", "send_sms"):
                response_text = "You're all set! Your appointment is confirmed and I've sent you a text with the details. Is there anything else I can help with?"
            else:
                response_text = "Is there anything else I can help you with?"

    return {
        "text": response_text,
        "end_call": should_end_call,
    }


def execute_tool(name: str, tool_input: dict) -> dict:
    match name:
        case "check_availability":
            return check_availability(tool_input["date"])
        case "book_appointment":
            return book_appointment(tool_input)
        case "send_sms":
            # Fire SMS in background to avoid blocking the voice response.
            # Twilio can take 5-10s which triggers VAPI idle timeout.
            threading.Thread(
                target=send_sms,
                args=(tool_input["to"], tool_input["message"]),
                daemon=True,
            ).start()
            return {"success": True, "message": "SMS is being sent"}
        case "log_call":
            threading.Thread(target=log_call, args=(tool_input,)).start()
            return {"success": True, "message": "Call logged"}
        case _:
            return {"error": f"Unknown tool: {name}"}
