"""Keep the genome overview's genome-wide aggregates in the cache, so a
visitor never pays the full-genome scan (see refresh_genome_overview_caches).
Run by the queue worker (tpweb_process_genome_queue) while it is idle."""

import logging
import time

from bioseq.models.Biodatabase import Biodatabase

from tpweb.services.assembly_workspace import refresh_genome_overview_caches

logger = logging.getLogger(__name__)


def warm_genome_caches(should_stop=lambda: False):
    """Refresh every genome's overview caches. Returns (genomes refreshed,
    seconds taken). A genome that fails is logged and skipped."""
    started = time.monotonic()
    proteomes = (
        Biodatabase.objects.filter(name__endswith=Biodatabase.PROT_POSTFIX)
        .order_by("name")
        .values_list("name", flat=True)
    )
    refreshed = 0
    for proteome in proteomes:
        if should_stop():
            break
        genome = proteome.removesuffix(Biodatabase.PROT_POSTFIX)
        try:
            refresh_genome_overview_caches(genome)
            refreshed += 1
        except Exception:
            logger.exception("Could not refresh overview caches for %s", genome)
    return refreshed, time.monotonic() - started
