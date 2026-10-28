"""Apply the call-data retention policy.

Clears call summaries/transcripts and masks caller numbers on CallLog rows
older than the retention window, keeping the row itself (duration, booked flag)
so dashboard statistics survive. Appointments are clinic records and are left
alone unless --appointments is passed, which anonymizes *past* appointments
older than the window.

Usage:
    python manage.py purge_call_data                # uses CALL_DATA_RETENTION_DAYS
    python manage.py purge_call_data --days 30 --dry-run
"""
from datetime import timedelta

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from calls import clinic
from calls.models import Appointment, CallLog
from calls.privacy import mask_phone

PURGED = "[purged]"


class Command(BaseCommand):
    help = "Purge call transcripts/summaries (and optionally appointment PII) past the retention window."

    def add_arguments(self, parser):
        parser.add_argument("--days", type=int, default=None, help="Retention window in days.")
        parser.add_argument("--appointments", action="store_true", help="Also anonymize past appointments.")
        parser.add_argument("--dry-run", action="store_true", help="Report what would change without writing.")

    def handle(self, *args, days=None, appointments=False, dry_run=False, **options):
        days = settings.CALL_DATA_RETENTION_DAYS if days is None else days
        if days < 1:
            raise CommandError("--days must be at least 1")
        cutoff = timezone.now() - timedelta(days=days)

        calls = CallLog.objects.filter(created_at__lt=cutoff).exclude(call_summary=PURGED)
        # Appointment.date is clinic-local, so compare against the clinic's calendar day.
        appts = Appointment.objects.filter(date__lt=clinic.today() - timedelta(days=days)).exclude(
            patient_name=PURGED
        )

        call_count = calls.count()
        appt_count = appts.count() if appointments else 0
        verb = "Would purge" if dry_run else "Purged"
        if not dry_run:
            with transaction.atomic():
                for call in calls.iterator():
                    call.call_summary = PURGED
                    if call.caller_phone:
                        call.caller_phone = mask_phone(call.caller_phone)
                    call.save(update_fields=["call_summary", "caller_phone"])
                if appointments:
                    for appt in appts.iterator():
                        appt.patient_name = PURGED
                        appt.patient_phone = mask_phone(appt.patient_phone)
                        appt.save(update_fields=["patient_name", "patient_phone"])

        self.stdout.write(
            f"{verb} {call_count} call log(s)"
            + (f" and {appt_count} appointment(s)" if appointments else "")
            + f" older than {days} day(s)."
        )
