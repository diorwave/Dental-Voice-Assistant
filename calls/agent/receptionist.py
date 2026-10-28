import json
import logging
import os
from datetime import datetime

from django.conf import settings
from openai import OpenAI

from .arguments import AvailabilityRequest, BookingRequest, ToolArgumentError
from .prompts import get_receptionist_prompt
from .tools import TOOLS
from ..services.calendar import book_appointment, check_availability
from ..services.sms import queue_booking_confirmation, spoken_datetime

logger = logging.getLogger(__name__)

MODEL = os.getenv("OPENAI_MODEL", "gpt-4o")

_client = None


def get_client():
    """Lazily create the OpenAI client so the app can boot without a key set."""
    global _client
    if _client is None:
        _client = OpenAI()  # reads OPENAI_API_KEY from the environment
    return _client


def _complete(messages: list):
    response = get_client().chat.completions.create(
        model=MODEL,
        max_tokens=1024,
        messages=messages,
        tools=TOOLS,
        tool_choice="auto",
        parallel_tool_calls=False,
    )
    return response.choices[0].message


def handle_conversation_turn(conversation_history: list, caller_phone: str = None, call_log=None) -> dict:
    """Run the agentic loop — the model keeps calling tools until done.
    Returns {"text": str, "end_call": bool}.

    `conversation_history` is a list of OpenAI-format messages with string
    content (role: "user" | "assistant"), as prepared by views.py.
    `call_log` is the CallLog for the live Vapi call (None for the web tester);
    appointments booked during the turn are linked to it.
    """
    system_prompt = get_receptionist_prompt()
    if caller_phone:
        system_prompt += f"\n\nCALLER INFO:\n- The caller's phone number is {caller_phone}. Use this number for the booking by default. Just confirm: \"We'll text the confirmation to the number you're calling from. Would you like it sent to a different number instead?\""

    messages = [{"role": "system", "content": system_prompt}] + list(conversation_history)

    msg = _complete(messages)

    should_end_call = False
    last_tool_name = None
    last_tool_result = None

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
                tool_result = execute_tool(name, args, call_log=call_log)
            except Exception as e:
                logger.error(f"[TOOL ERROR] {name}: {e}")
                tool_result = {"success": False, "error": "tool_failed", "message": "Temporary problem; apologize and offer to try again."}
            last_tool_result = tool_result
            logger.info(f"[RESULT] {json.dumps(tool_result)}")
            messages.append({
                "role": "tool",
                "tool_call_id": tc.id,
                "content": json.dumps(tool_result),
            })

        if should_end_call:
            break

        msg = _complete(messages)

    response_text = (msg.content or "").strip()

    # Fallback: if the model returned empty text after tools, say something
    # that matches what *actually* happened.
    if not response_text:
        if should_end_call:
            response_text = f"Thanks for calling {settings.CLINIC_NAME}. Have a great day, goodbye!"
        elif last_tool_name:
            logger.warning(f"[EMPTY RESPONSE] after tool={last_tool_name}, using fallback")
            response_text = fallback_reply(last_tool_name, last_tool_result)

    return {
        "text": response_text,
        "end_call": should_end_call,
    }


def fallback_reply(tool_name: str, result: dict | None) -> str:
    """A reply grounded in the last tool result, for when the model says nothing."""
    result = result or {}
    if tool_name == "book_appointment":
        if result.get("success"):
            when = spoken_datetime(datetime.fromisoformat(result["start"]))
            text = f"You're all set for {when}."
            if result.get("sms_confirmation") == "queued":
                text += " You'll get a text confirmation shortly."
            return text + " Is there anything else I can help with?"
        alternatives = result.get("alternatives") or []
        if result.get("error") == "slot_taken" and alternatives:
            return (
                f"Sorry, that time isn't available. I could do {' or '.join(alternatives)} instead. "
                "Would either of those work?"
            )
        return "Sorry, I wasn't able to book that just now. Could we try a different time?"
    if result and result.get("success") is False:
        return "Sorry, I didn't quite catch that. Could you tell me again?"
    return "Is there anything else I can help you with?"


def execute_tool(name: str, tool_input: dict, call_log=None) -> dict:
    try:
        return _dispatch_tool(name, tool_input, call_log)
    except ToolArgumentError as e:
        # Structured, recoverable error: the model can ask the caller to clarify.
        return e.as_result()


def _dispatch_tool(name: str, tool_input: dict, call_log=None) -> dict:
    match name:
        case "check_availability":
            return check_availability(AvailabilityRequest.from_args(tool_input))
        case "book_appointment":
            result = book_appointment(BookingRequest.from_args(tool_input), call=call_log)
            if result.get("success") and not result.get("already_booked"):
                # The only text we ever send: a fixed-template confirmation to the
                # phone stored on the appointment, queued server-side.
                from ..models import Appointment

                try:
                    appointment = Appointment.objects.get(pk=result["appointment_id"])
                    queued = queue_booking_confirmation(appointment)
                except Exception:
                    # The booking itself succeeded; never report it as failed
                    # because the confirmation text couldn't be queued.
                    logger.exception("[SMS] could not queue confirmation for appointment id=%s", result["appointment_id"])
                    queued = False
                result["sms_confirmation"] = "queued" if queued else "not_sent"
            return result
        case _:
            return {"success": False, "error": "unknown_tool", "message": f"Unknown tool: {name}"}
