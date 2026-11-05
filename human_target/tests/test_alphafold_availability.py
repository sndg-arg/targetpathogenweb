import unittest

from human_target.services.alphafold_availability import classify_predictions


class AlphaFoldAvailabilityTests(unittest.TestCase):
    def model(self, **changes):
        return {
            "entryId": "AF-P1-F1",
            "uniprotAccession": "P1",
            "uniprotSequence": "MKT",
            "uniprotStart": 1,
            "uniprotEnd": 3,
            "cifUrl": "https://example.org/model.cif",
            **changes,
        }

    def test_requires_exact_full_length_match(self):
        result = classify_predictions("P1", "MKT", [self.model()])
        self.assertEqual(result["status"], "available_matching")

    def test_fragment_is_not_eligible_even_with_full_uniprot_sequence(self):
        result = classify_predictions("P1", "MKT", [self.model(uniprotEnd=2)])
        self.assertEqual(result["status"], "needs_review")
        self.assertFalse(result["models"][0]["eligible"])

    def test_sequence_mismatch(self):
        result = classify_predictions("P1", "MKT", [self.model(uniprotSequence="MKA")])
        self.assertEqual(result["status"], "sequence_mismatch")

    def test_missing_metadata_needs_review(self):
        for changes in ({"uniprotSequence": None}, {"uniprotAccession": "P2"}, {"cifUrl": None}):
            with self.subTest(changes=changes):
                self.assertEqual(
                    classify_predictions("P1", "MKT", [self.model(**changes)])["status"],
                    "needs_review",
                )

    def test_empty_and_invalid_payloads_are_distinct(self):
        self.assertEqual(classify_predictions("P1", "MKT", [])["status"], "not_found")
        for payload in ({}, None, ["error"]):
            self.assertEqual(
                classify_predictions("P1", "MKT", payload)["status"], "invalid_response"
            )

    def test_checks_all_models(self):
        result = classify_predictions("P1", "MKT", [self.model(uniprotEnd=2), self.model()])
        self.assertEqual(result["status"], "available_matching")
