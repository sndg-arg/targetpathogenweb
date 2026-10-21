import unittest

from tpweb.services.score_param_types import is_boolean_score_series


class BooleanScoreSeriesTests(unittest.TestCase):
    def test_native_booleans_are_categorical(self):
        self.assertTrue(is_boolean_score_series([True, False, True]))

    def test_text_booleans_are_categorical(self):
        self.assertTrue(is_boolean_score_series(["True", "False"]))

    def test_single_boolean_value_is_categorical(self):
        self.assertTrue(is_boolean_score_series([True, True]))

    def test_missing_value_does_not_make_boolean_numeric(self):
        self.assertTrue(is_boolean_score_series([True, None, float("nan"), ""]))

    def test_empty_values_are_not_boolean(self):
        self.assertFalse(is_boolean_score_series([None, "", float("nan")]))

    def test_numeric_binary_scores_remain_numeric(self):
        self.assertFalse(is_boolean_score_series([0, 1]))
        self.assertFalse(is_boolean_score_series(["0", "1"]))

    def test_mixed_boolean_and_numeric_values_are_not_assumed_boolean(self):
        self.assertFalse(is_boolean_score_series(["True", "0"]))
