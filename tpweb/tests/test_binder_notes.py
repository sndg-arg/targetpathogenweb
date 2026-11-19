from django.test import SimpleTestCase

from tpweb.views.BinderDetailView import _clean_note_value


class BinderNoteValueTests(SimpleTestCase):
    def test_list_reprs_read_as_comma_separated(self):
        self.assertEqual(_clean_note_value("['PF00384' 'PF01568']"), "PF00384, PF01568")
        self.assertEqual(_clean_note_value("['PF1', 'X']"), "PF1, X")
        self.assertEqual(_clean_note_value("PF00384' 'PF01568"), "PF00384, PF01568")
