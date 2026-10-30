TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "check_availability",
            "description": (
                "List open start times (HH:MM, 24h, clinic local time) on a date for an "
                "appointment of the given type. Only slots where the whole appointment fits "
                "inside opening hours are returned."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "date": {
                        "type": "string",
                        "description": "The date to check, in YYYY-MM-DD format",
                    },
                    "appointment_type": {
                        "type": "string",
                        "enum": ["new_patient", "returning", "emergency"],
                        "description": "Determines appointment length. Defaults to returning (30 min).",
                    },
                },
                "required": ["date"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "book_appointment",
            "description": (
                "Book an appointment. Returns success=false with error=slot_taken and "
                "alternatives when the time is no longer free; never tell the caller they are "
                "booked unless success is true."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "date": {"type": "string", "description": "Date in YYYY-MM-DD format"},
                    "time": {"type": "string", "description": "Time in HH:MM format (24hr)"},
                    "patient_name": {"type": "string", "description": "Full name of patient"},
                    "patient_phone": {"type": "string", "description": "Phone number of patient"},
                    "appointment_type": {
                        "type": "string",
                        "enum": ["new_patient", "returning", "emergency"],
                        "description": "Type of appointment",
                    },
                },
                "required": ["date", "time", "patient_name", "patient_phone", "appointment_type"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "end_call",
            "description": "End the phone call. Use this after saying goodbye to the caller so the call disconnects automatically.",
            "parameters": {
                "type": "object",
                "properties": {
                    "reason": {
                        "type": "string",
                        "description": "Why the call is ending, e.g. 'booking_complete', 'caller_goodbye', 'no_further_questions'",
                    },
                },
                "required": ["reason"],
            },
        },
    },
]
