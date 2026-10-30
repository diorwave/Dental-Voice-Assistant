from django.contrib import admin
from .models import CallLog, Appointment


@admin.register(CallLog)
class CallLogAdmin(admin.ModelAdmin):
    list_display = ("caller_phone", "vapi_call_id", "appointment_booked", "duration_seconds", "created_at")
    list_filter = ("appointment_booked", "created_at")
    search_fields = ("caller_phone", "call_summary")
    readonly_fields = ("created_at",)


@admin.register(Appointment)
class AppointmentAdmin(admin.ModelAdmin):
    list_display = ("patient_name", "patient_phone", "appointment_type", "date", "time", "duration_minutes", "status", "sms_status", "created_at")
    list_filter = ("status", "appointment_type", "sms_status", "date")
    search_fields = ("patient_name", "patient_phone")
    readonly_fields = ("created_at", "google_event_id", "call", "sms_status", "sms_sid", "sms_error", "sms_updated_at")
