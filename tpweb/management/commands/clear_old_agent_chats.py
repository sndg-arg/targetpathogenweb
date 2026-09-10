from datetime import timedelta

from django.core.management.base import BaseCommand
from django.utils import timezone

from tpweb.models.AgentChatSession import AgentChatSession
from tpweb.services.agent_chat_sessions import HISTORY_RETENTION


class Command(BaseCommand):
    """Deletes assistant-drawer conversations past the retention window.

    Not wired into Celery beat -- this project's pipeline runs on direct
    subprocess orchestration, not Celery, and the broker isn't guaranteed to
    be configured in every deployment. Schedule this via a plain host/container
    cron entry instead, e.g. daily:
        0 3 * * * docker exec target2_nodo0_web bash -c \
            ". /opt/conda/etc/profile.d/conda.sh && conda activate tpv2 && \
            python manage.py clear_old_agent_chats"
    """

    help = "Delete AgentChatSession rows older than the retention window (default: 7 days)."

    def add_arguments(self, parser):
        parser.add_argument(
            "--days",
            type=int,
            default=HISTORY_RETENTION.days,
            help="Retention window in days (default: matches agent_chat_sessions' own retention).",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Show what would be deleted without actually deleting.",
        )

    def handle(self, *args, **options):
        cutoff = timezone.now() - timedelta(days=options["days"])
        qs = AgentChatSession.objects.filter(updated_at__lt=cutoff)
        count = qs.count()

        if options["dry_run"]:
            self.stdout.write(
                f"[dry-run] Would delete {count} conversation(s) older than {options['days']} day(s)"
            )
            return

        deleted, _details = qs.delete()
        self.stdout.write(f"Deleted {deleted} conversation(s) older than {options['days']} day(s)")
