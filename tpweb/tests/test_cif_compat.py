import unittest

from tpweb.services.cif_compat import quote_bare_cif_tokens


class CifCompatibilityTests(unittest.TestCase):
    def test_preserves_refinement_metadata_which_failed_for_3jpn(self):
        text = "_refine.pdbx_R_Free_selection_details '" + '"random"' + "'\n"
        self.assertEqual(quote_bare_cif_tokens(text), text)

    def test_quotes_prime_atom_names_without_changing_values(self):
        self.assertEqual(quote_bare_cif_tokens("ATOM 1 O5' C1'\n"), 'ATOM 1 "O5\'" "C1\'"\n')

    def test_preserves_quoted_compound_names(self):
        text = '_chem_comp.name "ADENOSINE-5\'-TRIPHOSPHATE"\n'
        self.assertEqual(quote_bare_cif_tokens(text), text)

    def test_preserves_multiline_text_and_comments(self):
        text = "# 'quoted comment\n_title\n;O5' and \"text\"\nmore ' text\n;\n"
        self.assertEqual(quote_bare_cif_tokens(text), text)

    def test_is_idempotent(self):
        text = quote_bare_cif_tokens("ATOM O5'\n")
        self.assertEqual(quote_bare_cif_tokens(text), text)
