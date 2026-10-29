"""Query AFDB for reviewed human proteins missing an active AlphaFold link."""

import json
import time
from collections import Counter

import requests
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from human_target.services.alphafold_availability import classify_predictions
from human_target.services.human_targets import human_proteins_queryset
from tpweb.models.BioentryStructure import BioentryStructure


class Command(BaseCommand):
    help = "Audit AFDB availability for missing reviewed proteins; no DB writes or model downloads."

    def add_arguments(self, parser):
        parser.add_argument("--accession", action="append", default=[])
        parser.add_argument("--timeout", type=int, default=30)

    def handle(self, *args, **options):
        if options["timeout"] <= 0:
            raise CommandError("--timeout must be positive")
        proteins = human_proteins_queryset().filter(is_reviewed=True)
        if options["accession"]:
            proteins = proteins.filter(uniprot_accession__in=options["accession"])
        linked = BioentryStructure.objects.filter(
            pdb__experiment="AF",
            pdb__deprecated=False,
        ).values("bioentry_id")
        rows = list(
            proteins.exclude(bioentry_id__in=linked)
            .order_by("uniprot_accession")
            .values_list("uniprot_accession", "sequence")
        )
        counts = Counter()
        self.stdout.write(
            json.dumps(
                {
                    "type": "start",
                    "at": timezone.now().isoformat(),
                    "scope": "reviewed_without_active_af_link",
                    "proteins": len(rows),
                    "note": "not_found is not proof of permanent unavailability or accession obsolescence",
                }
            )
        )
        self.stdout.flush()
        with requests.Session() as session:
            for index, (accession, sequence) in enumerate(rows, 1):
                url = f"https://alphafold.ebi.ac.uk/api/prediction/{accession}"
                status_code = None
                try:
                    response = session.get(url, timeout=options["timeout"])
                    status_code = response.status_code
                    if status_code == 404:
                        result = {"status": "not_found", "models": []}
                    else:
                        response.raise_for_status()
                        result = classify_predictions(accession, sequence, response.json())
                except requests.RequestException as exc:
                    result = {"status": "request_error", "error": str(exc), "models": []}
                except ValueError:
                    result = {"status": "invalid_response", "models": []}
                counts[result["status"]] += 1
                self.stdout.write(
                    json.dumps(
                        {
                            "type": "protein",
                            "accession": accession,
                            "checked_at": timezone.now().isoformat(),
                            "http_status": status_code,
                            **result,
                        }
                    )
                )
                self.stdout.flush()
                if status_code == 429:
                    # Preserve the partial report and avoid hammering a rate-limited service.
                    break
                if index < len(rows):
                    time.sleep(0.5)
        checked = sum(counts.values())
        self.stdout.write(
            json.dumps(
                {
                    "type": "summary",
                    "checked": checked,
                    "total": len(rows),
                    "not_checked": len(rows) - checked,
                    "counts": dict(counts),
                }
            )
        )
        if checked != len(rows) or counts["request_error"] or counts["invalid_response"]:
            raise CommandError(
                "Audit incomplete: see request errors/unqueried proteins in the JSONL report"
            )
