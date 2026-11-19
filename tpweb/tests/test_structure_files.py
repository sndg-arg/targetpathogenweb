from types import SimpleNamespace
from unittest import mock

from django.test import SimpleTestCase

from tpweb.models.BioentryStructure import BioentryStructure
from tpweb.services import structure_files


class LinkedStructureFilePathTests(SimpleTestCase):
    def _links(self, accessions):
        manager = mock.MagicMock()
        chain = manager.filter.return_value.exclude.return_value.values_list.return_value
        chain.distinct.return_value = accessions
        return manager

    def test_shared_pdb_falls_back_to_the_chain_that_stored_the_file(self):
        def stored_under_p2(genome, accession, code):
            if accession == "P2":
                return f"/data/{genome}/{accession}/{code}.cif.gz"
            raise FileNotFoundError(accession)

        pdb = SimpleNamespace(code="5HHM")
        with (
            mock.patch.object(structure_files, "structure_file_path", side_effect=stored_under_p2),
            mock.patch.object(BioentryStructure, "objects", self._links(["P2"])),
        ):
            path = structure_files.linked_structure_file_path("human", "P1", pdb)
        self.assertEqual(path, "/data/human/P2/5HHM.cif.gz")

    def test_still_raises_when_no_linked_protein_has_the_file(self):
        pdb = SimpleNamespace(code="5HHM")
        with (
            mock.patch.object(
                structure_files, "structure_file_path", side_effect=FileNotFoundError("x")
            ),
            mock.patch.object(BioentryStructure, "objects", self._links(["P2"])),
            self.assertRaises(FileNotFoundError),
        ):
            structure_files.linked_structure_file_path("human", "P1", pdb)
