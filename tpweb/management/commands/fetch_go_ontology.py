from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from bioseq.models.Dbxref import Dbxref
from bioseq.models.Ontology import Ontology
from bioseq.models.Term import Term
from bioseq.models.TermDbxref import TermDbxref
from tpweb.services.go_ontology import GO_BASIC_OBO_URL, download_go_obo, expand_go_records, parse_go_obo


class Command(BaseCommand):
    help = (
        "Download the official Gene Ontology (go-basic.obo) and sync GO terms, "
        "definitions, and alt_id aliases into the local bioseq tables."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--url",
            default=GO_BASIC_OBO_URL,
            help=f"Ontology URL to download (default: {GO_BASIC_OBO_URL})",
        )
        parser.add_argument(
            "--obo-path",
            default="",
            help="Optional local OBO path. If provided, skip downloading and read this file instead.",
        )
        parser.add_argument(
            "--timeout",
            type=int,
            default=60,
            help="HTTP timeout in seconds when downloading the ontology.",
        )
        parser.add_argument(
            "--batch-size",
            type=int,
            default=2000,
            help="Bulk create/update batch size.",
        )

    def _load_text(self, options):
        obo_path = str(options["obo_path"] or "").strip()
        if obo_path:
            path = Path(obo_path)
            if not path.exists():
                raise CommandError(f"OBO file not found: {path}")
            self.stdout.write(f"Reading {path} ...")
            return path.read_text(encoding="utf-8", errors="replace")

        url = str(options["url"] or "").strip()
        if not url:
            raise CommandError("Either --url or --obo-path is required")
        self.stdout.write(f"Downloading {url} ...")
        return download_go_obo(url=url, timeout=options["timeout"])

    def handle(self, *args, **options):
        text = self._load_text(options)
        records = parse_go_obo(text)
        resolved_terms = expand_go_records(records)
        batch_size = int(options["batch_size"])

        if not records:
            raise CommandError("No GO terms were parsed from the supplied ontology source")

        self.stdout.write(
            f"Parsed {len(records):,} primary GO terms and {len(resolved_terms):,} total identifiers including alt_id aliases"
        )

        go_ontology, _ = Ontology.objects.get_or_create(name=Ontology.GO, defaults={"definition": ""})

        incoming_by_id = {term.identifier: term for term in resolved_terms}
        incoming_ids = list(incoming_by_id.keys())

        existing_terms = {
            term.identifier: term
            for term in Term.objects.filter(ontology=go_ontology, identifier__in=incoming_ids)
        }
        existing_dbxrefs = {
            dbxref.accession: dbxref
            for dbxref in Dbxref.objects.filter(dbname=Ontology.GO, accession__in=incoming_ids)
        }

        terms_to_create = []
        terms_to_update = []
        for identifier, incoming in incoming_by_id.items():
            existing = existing_terms.get(identifier)
            if existing is None:
                terms_to_create.append(
                    Term(
                        ontology=go_ontology,
                        identifier=identifier,
                        name=incoming.name or identifier,
                        definition=incoming.definition or "",
                        version=0,
                        is_obsolete="Y" if incoming.is_obsolete else "N",
                    )
                )
                continue

            changed = False
            desired_name = incoming.name or identifier
            desired_definition = incoming.definition or ""
            desired_obsolete = "Y" if incoming.is_obsolete else "N"
            if existing.name != desired_name:
                existing.name = desired_name
                changed = True
            if (existing.definition or "") != desired_definition:
                existing.definition = desired_definition
                changed = True
            if getattr(existing, "is_obsolete", "N") != desired_obsolete:
                existing.is_obsolete = desired_obsolete
                changed = True
            if changed:
                terms_to_update.append(existing)

        if terms_to_create:
            Term.objects.bulk_create(terms_to_create, batch_size=batch_size)
        if terms_to_update:
            Term.objects.bulk_update(terms_to_update, ["name", "definition", "is_obsolete"], batch_size=batch_size)

        term_id_map = {
            term.identifier: term
            for term in Term.objects.filter(ontology=go_ontology, identifier__in=incoming_ids)
        }

        dbxrefs_to_create = [
            Dbxref(dbname=Ontology.GO, accession=identifier, version=0)
            for identifier in incoming_ids
            if identifier not in existing_dbxrefs
        ]
        if dbxrefs_to_create:
            Dbxref.objects.bulk_create(dbxrefs_to_create, batch_size=batch_size)

        dbxref_id_map = {
            dbxref.accession: dbxref
            for dbxref in Dbxref.objects.filter(dbname=Ontology.GO, accession__in=incoming_ids)
        }

        existing_links = set(
            TermDbxref.objects.filter(
                term__ontology=go_ontology,
                dbxref__dbname=Ontology.GO,
                dbxref__accession__in=incoming_ids,
            ).values_list("term_id", "dbxref_id")
        )

        links_to_create = []
        for identifier in incoming_ids:
            term = term_id_map[identifier]
            dbxref = dbxref_id_map[identifier]
            key = (term.pk, dbxref.pk)
            if key in existing_links:
                continue
            links_to_create.append(TermDbxref(term=term, dbxref=dbxref, rank=0))

        if links_to_create:
            TermDbxref.objects.bulk_create(links_to_create, batch_size=batch_size)

        obsolete_total = sum(1 for term in resolved_terms if term.is_obsolete)
        alias_total = max(0, len(resolved_terms) - len(records))
        self.stdout.write(
            self.style.SUCCESS(
                "GO ontology synced: "
                f"{len(records):,} primary terms, "
                f"{alias_total:,} alt_id aliases, "
                f"{obsolete_total:,} obsolete identifiers, "
                f"{len(terms_to_create):,} new terms, "
                f"{len(terms_to_update):,} updated terms, "
                f"{len(dbxrefs_to_create):,} new dbxrefs, "
                f"{len(links_to_create):,} new term-dbxref links"
            )
        )
