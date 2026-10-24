from django.test import TestCase

from bioseq.models.Biodatabase import Biodatabase
from bioseq.models.Bioentry import Bioentry
from bioseq.models.Ontology import Ontology
from bioseq.models.Seqfeature import Seqfeature
from bioseq.models.Term import Term
from tpweb.services.protein_list import (
    add_selected_parameter,
    apply_selected_parameter_filters,
    build_special_filter_payload,
)


class TransmembraneFilterTests(TestCase):
    def _feature(self, entry, db, identifier):
        ontology, _ = Ontology.objects.get_or_create(name=db)
        term, _ = Term.objects.get_or_create(
            ontology=ontology, identifier=identifier, defaults={"name": identifier}
        )
        Seqfeature.objects.create(bioentry=entry, type_term=term, source_term=term)

    def _filtered(self, proteins, value):
        return sorted(
            apply_selected_parameter_filters(
                proteins, [build_special_filter_payload("tm", value)]
            ).values_list("accession", flat=True)
        )

    def test_filters_on_predicted_membrane_segments(self):
        proteome = Biodatabase.objects.create(name="TM_protein")
        entries = {
            accession: Bioentry.objects.create(
                biodatabase=proteome, name=accession, accession=accession, identifier=accession
            )
            for accession in ("PHOBIUS", "TMHMM", "SOLUBLE", "BARE")
        }
        self._feature(entries["PHOBIUS"], "Phobius", "TRANSMEMBRANE")
        self._feature(entries["TMHMM"], "TMHMM", "TMhelix")
        # Topology domains and other databases are not membrane segments.
        self._feature(entries["SOLUBLE"], "Phobius", "CYTOPLASMIC_DOMAIN")
        self._feature(entries["SOLUBLE"], "Pfam", "TRANSMEMBRANE")
        proteins = Bioentry.objects.filter(biodatabase=proteome)

        self.assertEqual(self._filtered(proteins, "yes"), ["PHOBIUS", "TMHMM"])
        self.assertEqual(self._filtered(proteins, "no"), ["BARE", "SOLUBLE"])

    def test_payload_is_yes_no_and_mutually_exclusive(self):
        self.assertIsNone(build_special_filter_payload("tm", "maybe"))
        selected = add_selected_parameter([], build_special_filter_payload("tm", "yes"))
        selected = add_selected_parameter(selected, build_special_filter_payload("tm", "no"))
        self.assertEqual([item["id"] for item in selected], ["special:tm:no"])
        # Another yes/no filter is kept alongside.
        selected = add_selected_parameter(selected, build_special_filter_payload("ligands", "yes"))
        self.assertEqual(len(selected), 2)
