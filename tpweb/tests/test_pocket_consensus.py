from unittest.mock import Mock

from django.test import SimpleTestCase

from tpweb.services.pocket_consensus import (
    POCKET_CONSENSUS_DISTANCE,
    center_distance,
    nearest_named_center,
    pocket_residue_overlap,
    residue_identity,
)


def _residue(chain, resid, icode=""):
    return Mock(chain=chain, resid=resid, icode=icode)


class CenterDistanceTests(SimpleTestCase):
    def test_distance_between_two_points(self):
        self.assertAlmostEqual(center_distance((0, 0, 0), (3, 4, 0)), 5.0)

    def test_none_input_returns_none(self):
        self.assertIsNone(center_distance(None, (1, 1, 1)))
        self.assertIsNone(center_distance((1, 1, 1), None))


class NearestNamedCenterTests(SimpleTestCase):
    def test_returns_the_closest_label_and_distance(self):
        named_centers = [
            ("P2Rank 1", (10, 10, 10)),
            ("P2Rank 2", (0, 0, 1)),
        ]
        label, distance = nearest_named_center((0, 0, 0), named_centers)

        self.assertEqual(label, "P2Rank 2")
        self.assertAlmostEqual(distance, 1.0)

    def test_empty_candidates_returns_none(self):
        self.assertIsNone(nearest_named_center((0, 0, 0), []))

    def test_within_consensus_distance_is_a_realistic_same_site_case(self):
        # Two predictors rarely agree on the exact same center -- a few
        # angstroms apart is the expected "same site" case this constant
        # exists to cover.
        label, distance = nearest_named_center((0, 0, 0), [("FPocket 3", (4, 3, 0))])
        self.assertEqual(label, "FPocket 3")
        self.assertLess(distance, POCKET_CONSENSUS_DISTANCE)


class ResidueIdentityTests(SimpleTestCase):
    def test_identity_is_chain_resid_icode_tuple(self):
        residue = _residue("A", 42, "")
        self.assertEqual(residue_identity(residue), ("A", 42, ""))

    def test_same_resid_different_chain_are_distinct(self):
        self.assertNotEqual(
            residue_identity(_residue("A", 42)), residue_identity(_residue("B", 42))
        )


class PocketResidueOverlapTests(SimpleTestCase):
    def test_full_overlap(self):
        residues = [_residue("A", i) for i in range(1, 6)]

        overlap = pocket_residue_overlap(residues, residues)

        self.assertEqual(overlap["shared_count"], 5)
        self.assertAlmostEqual(overlap["smaller_coverage"], 100.0)
        self.assertAlmostEqual(overlap["jaccard"], 100.0)

    def test_partial_overlap_does_not_conflate_across_chains(self):
        left = [_residue("A", 1), _residue("A", 2), _residue("B", 3)]
        right = [_residue("A", 1), _residue("C", 2), _residue("B", 3)]

        overlap = pocket_residue_overlap(left, right)

        # Only (A,1) and (B,3) match -- (A,2) vs (C,2) share a resid but not
        # a chain, and must not be counted as shared.
        self.assertEqual(overlap["shared_count"], 2)
        self.assertAlmostEqual(overlap["smaller_coverage"], 2 / 3 * 100)

    def test_no_overlap(self):
        left = [_residue("A", 1)]
        right = [_residue("A", 2)]

        overlap = pocket_residue_overlap(left, right)

        self.assertEqual(overlap["shared_count"], 0)
        self.assertEqual(overlap["smaller_coverage"], 0.0)
        self.assertEqual(overlap["jaccard"], 0.0)

    def test_empty_inputs_do_not_divide_by_zero(self):
        overlap = pocket_residue_overlap([], [])

        self.assertEqual(overlap["shared_count"], 0)
        self.assertEqual(overlap["smaller_coverage"], 0.0)
        self.assertEqual(overlap["jaccard"], 0.0)
