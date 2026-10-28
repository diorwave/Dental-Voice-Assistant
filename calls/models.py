from django.db import models


class CallLog(models.Model):
    # Vapi's call id. Unique so the per-turn upsert and the end-of-call webhook
    # write to the same row instead of creating duplicates. Null for legacy rows
    # and for reports that arrive without an id.
    vapi_call_id = models.CharField(max_length=64, unique=True, null=True, blank=True)
    caller_phone = models.CharField(max_length=20, blank=True)
    call_summary = models.TextField(blank=True)
    appointment_booked = models.BooleanField(default=False)
    duration_seconds = models.IntegerField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.caller_phone} — {'Booked' if self.appointment_booked else 'No booking'}"


class Appointment(models.Model):
    STATUS_BOOKED = "booked"
    STATUS_CANCELLED = "cancelled"
    STATUSES = [(STATUS_BOOKED, "Booked"), (STATUS_CANCELLED, "Cancelled")]

    patient_name = models.CharField(max_length=100)
    patient_phone = models.CharField(max_length=20)
    appointment_type = models.CharField(
        max_length=20,
        choices=[
            ("new_patient", "New Patient"),
            ("returning", "Returning"),
            ("emergency", "Emergency"),
        ],
    )
    date = models.DateField()
    time = models.TimeField()
    duration_minutes = models.IntegerField(default=30)
    status = models.CharField(max_length=10, choices=STATUSES, default=STATUS_BOOKED)
    google_event_id = models.CharField(max_length=255, blank=True)
    call = models.ForeignKey(
        CallLog, null=True, blank=True, on_delete=models.SET_NULL, related_name="appointments"
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-date", "-time"]
        constraints = [
            # Backstop against two concurrent calls booking the same start time.
            models.UniqueConstraint(
                fields=["date", "time"],
                condition=models.Q(status="booked"),
                name="unique_booked_appointment_start",
            ),
        ]

    def __str__(self):
        return f"{self.patient_name} — {self.date} {self.time}"
