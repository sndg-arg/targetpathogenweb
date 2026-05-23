import fcntl
import signal
import time
from pathlib import Path

from django.core.management.base import BaseCommand

from tpweb.models import GenomeUpload
from tpweb.services.genome_upload_status import reconcile_genome_uploads
from tpweb.services.genome_uploads import dequeue_next_genome_upload, run_genome_upload_pipeline
from tpweb.services.pipeline_status import get_pipeline_status


class Command(BaseCommand):
    help = "Processes queued genome uploads serially."
    lock_path = Path("/tmp/tpweb_genome_upload_queue.lock")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._shutdown_requested = False

    def add_arguments(self, parser):
        parser.add_argument(
            "--poll-interval",
            type=float,
            default=5.0,
            help="Seconds to wait between queue polling attempts.",
        )
        parser.add_argument(
            "--once",
            action="store_true",
            help="Process at most one queued upload and exit.",
        )

    def _request_shutdown(self, signum, frame):
        sig_name = signal.Signals(signum).name
        self.stdout.write(f"Received {sig_name} — finishing current job before shutdown.")
        self._shutdown_requested = True

    def handle(self, *args, **options):
        poll_interval = max(0.5, float(options["poll_interval"]))
        run_once = bool(options["once"])

        signal.signal(signal.SIGTERM, self._request_shutdown)
        signal.signal(signal.SIGINT, self._request_shutdown)

        self.lock_path.parent.mkdir(parents=True, exist_ok=True)
        with self.lock_path.open("w") as lock_handle:
            try:
                fcntl.flock(lock_handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                self.stdout.write("Genome upload queue worker is already running.")
                return

            self.stdout.write("Genome upload queue worker started.")
            while not self._shutdown_requested:
                processed = self._process_next_upload()
                if run_once:
                    return
                if not processed and not self._shutdown_requested:
                    time.sleep(poll_interval)

            self.stdout.write("Genome upload queue worker stopped gracefully.")

    def _process_next_upload(self):
        pipeline_status = get_pipeline_status()
        reconcile_genome_uploads(pipeline_status)

        if pipeline_status.get("running"):
            return False
        if GenomeUpload.objects.filter(status=GenomeUpload.STATUS_RUNNING).exists():
            return False

        upload = dequeue_next_genome_upload()
        if upload is None:
            return False

        self.stdout.write(
            f"Processing genome upload #{upload.id} for {upload.owner.username}: {upload.display_accession}"
        )
        final_status = run_genome_upload_pipeline(upload)
        self.stdout.write(f"Genome upload #{upload.id} finished with status={final_status}.")
        return True
