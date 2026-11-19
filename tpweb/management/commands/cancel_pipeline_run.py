from django.core.management.base import BaseCommand, CommandError

from tpweb.models import PipelineRun
from tpweb.services.genome_upload_status import reconcile_genome_uploads
from tpweb.services.pipeline_runs import cancel_pipeline_run


class Command(BaseCommand):
    help = (
        "Cancel a pipeline run that is stuck in submitted/running (e.g. its process was "
        "stopped by hand) so the genome can be run again. By default the recorded process "
        "is NOT signalled: its PID belongs to the container that launched it and may have "
        "been reused. Pass --kill to signal it when you know it is still the orchestrator."
    )

    def add_arguments(self, parser):
        parser.add_argument("run_id", type=int)
        parser.add_argument(
            "--kill",
            action="store_true",
            help="Also send SIGTERM/SIGKILL to the recorded launch PID (run inside `queue`).",
        )

    def handle(self, *args, run_id, kill, **options):
        run = PipelineRun.objects.filter(pk=run_id).first()
        if run is None:
            raise CommandError(f"Pipeline run {run_id} does not exist.")
        if run.status not in {PipelineRun.STATUS_SUBMITTED, PipelineRun.STATUS_RUNNING}:
            raise CommandError(f"Pipeline run {run_id} is already {run.status}.")

        if not kill and run.launch_pid is not None:
            run.launch_pid = None
            run.save(update_fields=["launch_pid"])
        cancel_pipeline_run(run)
        reconcile_genome_uploads()

        run.refresh_from_db()
        self.stdout.write(
            self.style.SUCCESS(
                f"Pipeline run {run.id} ({run.internal_accession}) is now {run.status}."
            )
        )
