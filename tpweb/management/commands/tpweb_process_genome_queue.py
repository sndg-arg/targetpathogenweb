import fcntl
import os
import signal
import time
from pathlib import Path

from django.core.management.base import BaseCommand

from tpweb.models import GenomeUpload
from tpweb.services.cache_warming import warm_genome_caches
from tpweb.services.genome_upload_status import reconcile_genome_uploads
from tpweb.services.genome_uploads import dequeue_next_genome_upload, run_genome_upload_pipeline
from tpweb.services.pipeline_status import get_pipeline_status


class Command(BaseCommand):
    help = "Processes queued genome uploads serially."
    lock_path = Path("/tmp/tpweb_genome_upload_queue.lock")
    # Below the overview caches' 15-minute TTL, so they never expire between
    # refreshes. 0 disables warming.
    cache_warm_interval = int(os.environ.get("TPW_CACHE_WARM_INTERVAL_SEC", "600"))

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._shutdown_requested = False
        self._pipeline_running = False
        self._next_cache_warm = 0.0

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
                if processed:
                    # New data: refresh the caches as soon as the queue is idle.
                    self._next_cache_warm = 0.0
                elif not self._shutdown_requested:
                    self._warm_caches_if_due()
                    time.sleep(poll_interval)

            self.stdout.write("Genome upload queue worker stopped gracefully.")

    def _warm_caches_if_due(self):
        if self.cache_warm_interval <= 0 or self._pipeline_running:
            return
        if time.monotonic() < self._next_cache_warm:
            return
        refreshed, seconds = warm_genome_caches(lambda: self._shutdown_requested)
        self.stdout.write(f"Refreshed overview caches for {refreshed} genomes in {seconds:.1f}s.")
        self._next_cache_warm = time.monotonic() + self.cache_warm_interval

    def _process_next_upload(self):
        pipeline_status = get_pipeline_status()
        reconcile_genome_uploads(pipeline_status)

        self._pipeline_running = (
            bool(pipeline_status.get("running"))
            or GenomeUpload.objects.filter(status=GenomeUpload.STATUS_RUNNING).exists()
        )
        if self._pipeline_running:
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
