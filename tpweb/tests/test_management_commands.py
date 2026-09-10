"""Tests for management commands with no bioseq model dependency -- pure
tpweb models whose schema this test file can read directly, so fixtures
here are built from source, not guessed.
"""

from datetime import timedelta
from io import StringIO

from django.core.management import call_command
from django.test import TestCase
from django.utils import timezone

from tpweb.models.AgentChatSession import AgentChatSession
from tpweb.management.commands.fetch_ec_nomenclature import (
    build_hierarchy_labels,
    parse_enzclass_txt,
    parse_enzyme_dat,
)
from tpweb.management.commands.run_curated_file_import import (
    _detect_archive_root,
    _is_within,
    _quote_join,
    _resolve_workdir,
    _strip_root,
    _unsafe_member,
)
from tpweb.management.commands.curated_selected_source_report import (
    code_matches,
    format_percent,
    identifier_candidates,
    raw_score,
    structure_kind,
)
from tpweb.management.commands.dedup_features import _location_key
from tpweb.management.commands.import_gates_pocket_outputs import (
    clean as gates_clean,
    colabfold_sources,
    is_no_pocket,
    is_pdb_code as gates_is_pdb_code,
    parse_pdb_chain_source,
    selected_sources,
)
from tpweb.management.commands.selected_pdb_pocket_report import (
    _clean as pdb_report_clean,
    _is_expected_no_pockets,
    _is_pdb_code as pdb_report_is_pdb_code,
)
from tpweb.management.commands._shared import is_pdb_code as af_is_pdb_code
from tpweb.management.commands.export_selected_alphafold_pocket_jobs import (
    clean as af_clean,
    folder_path as af_folder_path,
    is_alphafold_uniprot_source,
    norm_source,
    structure_code,
)
from tpweb.management.commands.export_selected_pdb_pocket_jobs import (
    _clean as pdb_export_clean,
    _folder_path as pdb_export_folder_path,
    _is_pdb_code as pdb_export_is_pdb_code,
    _parse_structure_candidates,
)
from tpweb.management.commands.load_csa import (
    _clean_optional_text,
    _parse_residue_identifier,
    _site_storage_name,
)
from tpweb.management.commands.import_curated_uniprot import (
    _compute_folder_path as curated_uniprot_folder_path,
    _parse_uniprot_accessions,
)
from tpweb.management.commands.selected_alphafold_source_report import is_loaded


class ClearOldAgentChatsTests(TestCase):
    def _create_session(self, key, days_old):
        session = AgentChatSession.objects.create(session_key=key, history_json=[])
        # updated_at is auto_now=True, so Model.save() always overwrites it --
        # backdate via a queryset .update(), which bypasses auto_now.
        backdated = timezone.now() - timedelta(days=days_old)
        AgentChatSession.objects.filter(pk=session.pk).update(updated_at=backdated)
        return session

    def test_deletes_only_sessions_older_than_retention_window(self):
        self._create_session("old-session", days_old=10)
        self._create_session("recent-session", days_old=1)

        call_command("clear_old_agent_chats", stdout=StringIO())

        remaining = set(AgentChatSession.objects.values_list("session_key", flat=True))
        self.assertEqual(remaining, {"recent-session"})

    def test_dry_run_deletes_nothing(self):
        self._create_session("old-session", days_old=10)

        call_command("clear_old_agent_chats", "--dry-run", stdout=StringIO())

        self.assertTrue(AgentChatSession.objects.filter(session_key="old-session").exists())

    def test_custom_days_argument_overrides_default_ttl(self):
        self._create_session("three-days-old", days_old=3)

        call_command("clear_old_agent_chats", "--days=2", stdout=StringIO())

        self.assertFalse(AgentChatSession.objects.filter(session_key="three-days-old").exists())


class ParseEnzymeDatTests(TestCase):
    """fetch_ec_nomenclature.py rebuilds tpweb/data/ec_hierarchy_labels.json,
    which drives the Annotation Explorer's EC hierarchy -- these pure parsers
    have no DB/network dependency, so get exact fixture control over ExPASy's
    format instead of guessing at real downloaded content."""

    def test_extracts_level_4_enzyme_name_and_strips_trailing_period(self):
        text = "ID   1.1.1.1\nDE   Alcohol dehydrogenase.\n//\n"

        result = parse_enzyme_dat(text)

        self.assertEqual(result, {"1.1.1.1": "Alcohol dehydrogenase"})

    def test_joins_multiline_de_field_with_spaces(self):
        text = "ID   1.1.1.3\nDE   Homoserine\nDE   dehydrogenase.\n//\n"

        result = parse_enzyme_dat(text)

        self.assertEqual(result, {"1.1.1.3": "Homoserine dehydrogenase"})

    def test_skips_transferred_and_deleted_entries(self):
        text = (
            "ID   1.1.1.2\n"
            "DE   Transferred entry: 1.1.1.71.\n"
            "//\n"
            "ID   1.1.1.199\n"
            "DE   Deleted entry.\n"
            "//\n"
        )

        result = parse_enzyme_dat(text)

        self.assertEqual(result, {})


class ParseEnzclassTxtTests(TestCase):
    def test_dash_third_component_is_a_subclass(self):
        text = "1. 1.-.-  Oxidoreductases acting on donors\n"

        subclass_labels, subsubclass_labels = parse_enzclass_txt(text)

        self.assertEqual(subclass_labels, {"1.1": "Oxidoreductases acting on donors"})
        self.assertEqual(subsubclass_labels, {})

    def test_numeric_third_component_is_a_subsubclass(self):
        text = "1. 1. 1.-  Acting on the CH-OH group of donors\n"

        subclass_labels, subsubclass_labels = parse_enzclass_txt(text)

        self.assertEqual(subclass_labels, {})
        self.assertEqual(subsubclass_labels, {"1.1.1": "Acting on the CH-OH group of donors"})

    def test_non_matching_lines_are_ignored(self):
        text = "This is a comment line, not an EC class entry.\n"

        subclass_labels, subsubclass_labels = parse_enzclass_txt(text)

        self.assertEqual(subclass_labels, {})
        self.assertEqual(subsubclass_labels, {})


class BuildHierarchyLabelsTests(TestCase):
    def test_combines_all_levels_under_expected_keys(self):
        result = build_hierarchy_labels(
            enzyme_names={"1.1.1.1": "Alcohol dehydrogenase"},
            subclass_labels={"1.1": "Oxidoreductases acting on donors"},
            subsubclass_labels={"1.1.1": "Acting on the CH-OH group of donors"},
        )

        self.assertEqual(result["enzyme_names"], {"1.1.1.1": "Alcohol dehydrogenase"})
        self.assertEqual(result["subclass_labels"], {"1.1": "Oxidoreductases acting on donors"})
        self.assertIn("class_labels", result)
        self.assertEqual(result["class_labels"]["1"], "Oxidoreductases")


class RunCuratedFileImportHelperTests(TestCase):
    """run_curated_file_import.py extracts a tarball of curated results onto
    the filesystem -- these helpers are the path-safety layer (reject
    absolute paths and ../ escapes) plus archive-root detection, so gaps here
    are directory-traversal bugs, not just cosmetic ones."""

    def test_resolve_workdir_prefers_explicit_value(self):
        self.assertEqual(_resolve_workdir("/explicit", "/app/data"), "/explicit")

    def test_resolve_workdir_strips_trailing_data_segment(self):
        self.assertEqual(
            _resolve_workdir(None, "/app/targetpathogenweb/data/"), "/app/targetpathogenweb"
        )

    def test_resolve_workdir_falls_back_to_cwd_marker(self):
        self.assertEqual(_resolve_workdir(None, "/app/targetpathogenweb/other"), ".")

    def test_quote_join_quotes_parts_with_spaces_and_drops_empty(self):
        self.assertEqual(_quote_join(["a", "b c", ""]), "a 'b c'")

    def test_detect_archive_root_returns_common_first_segment(self):
        names = ["curated/results.tsv", "curated/structures/1abc.pdb"]
        self.assertEqual(_detect_archive_root(names), "curated")

    def test_detect_archive_root_returns_empty_when_multiple_roots(self):
        names = ["curated/results.tsv", "other/structures/1abc.pdb"]
        self.assertEqual(_detect_archive_root(names), "")

    def test_strip_root_removes_matching_prefix(self):
        self.assertEqual(
            _strip_root("curated/structures/1abc.pdb", "curated"), "structures/1abc.pdb"
        )

    def test_strip_root_normalizes_backslashes(self):
        self.assertEqual(
            _strip_root("curated\\structures\\1abc.pdb", "curated"), "structures/1abc.pdb"
        )

    def test_strip_root_leaves_non_matching_name_untouched(self):
        self.assertEqual(_strip_root("other/file.txt", "curated"), "other/file.txt")

    def test_unsafe_member_flags_absolute_and_traversal_paths(self):
        self.assertTrue(_unsafe_member("/etc/passwd"))
        self.assertTrue(_unsafe_member("../etc/passwd"))
        self.assertTrue(_unsafe_member("curated/../../etc/passwd"))
        self.assertTrue(_unsafe_member(".."))

    def test_unsafe_member_allows_normal_relative_paths(self):
        self.assertFalse(_unsafe_member("curated/structures/1abc.pdb"))

    def test_is_within_true_for_nested_path(self):
        self.assertTrue(_is_within("/tmp/workdir", "/tmp/workdir/sub/file.txt"))

    def test_is_within_false_for_sibling_path(self):
        self.assertFalse(_is_within("/tmp/workdir", "/tmp/other/file.txt"))


class CuratedSelectedSourceReportTests(TestCase):
    def test_raw_score_normalizes_missing_markers_to_empty_string(self):
        self.assertEqual(raw_score(None), "")
        self.assertEqual(raw_score("  nan  "), "")
        self.assertEqual(raw_score("1abc"), "1abc")

    def test_structure_kind_classifies_missing_identifier(self):
        self.assertEqual(structure_kind(""), "missing")

    def test_structure_kind_classifies_pdb_code(self):
        self.assertEqual(structure_kind("1ABC"), "PDB")

    def test_structure_kind_classifies_colabfold_curated(self):
        self.assertEqual(structure_kind("CB_LOCUS1"), "ColabFold/curated")

    def test_structure_kind_classifies_alphafold_uniprot(self):
        self.assertEqual(structure_kind("AF_P12345"), "AlphaFold/UniProt")
        self.assertEqual(structure_kind("P12345"), "AlphaFold/UniProt")

    def test_structure_kind_falls_back_to_curated_model(self):
        self.assertEqual(structure_kind("FOOBAR"), "Curated/model")

    def test_identifier_candidates_strips_known_prefixes(self):
        candidates = identifier_candidates("AF_P12345")
        self.assertIn("P12345", candidates)
        self.assertIn("AF_P12345", candidates)

    def test_code_matches_accepts_chain_suffixed_code(self):
        self.assertTrue(code_matches("1ABC_A", "1ABC"))

    def test_code_matches_rejects_unrelated_code(self):
        self.assertFalse(code_matches("1ABCX", "1ABC"))

    def test_code_matches_rejects_empty_code(self):
        self.assertFalse(code_matches("", "1ABC"))

    def test_format_percent_formats_ratio(self):
        self.assertEqual(format_percent(1, 4), "25.0%")

    def test_format_percent_handles_zero_total(self):
        self.assertEqual(format_percent(0, 0), "0.0%")


class DedupFeaturesLocationKeyTests(TestCase):
    """_location_key feeds a dict used to detect duplicate SeqFeature rows --
    it must be order-independent so re-running load_interpro against features
    saved in a different iteration order still dedupes correctly."""

    class _FakeLocation:
        def __init__(self, start_pos, end_pos, strand):
            self.start_pos = start_pos
            self.end_pos = end_pos
            self.strand = strand

    class _FakeLocationManager:
        def __init__(self, locations):
            self._locations = locations

        def all(self):
            return self._locations

    class _FakeFeature:
        def __init__(self, locations):
            self.locations = DedupFeaturesLocationKeyTests._FakeLocationManager(locations)

    def test_location_key_sorts_locations_regardless_of_input_order(self):
        forward_order = self._FakeFeature(
            [self._FakeLocation(10, 20, 1), self._FakeLocation(1, 5, 1)]
        )
        reverse_order = self._FakeFeature(
            [self._FakeLocation(1, 5, 1), self._FakeLocation(10, 20, 1)]
        )

        self.assertEqual(_location_key(forward_order), _location_key(reverse_order))
        self.assertEqual(_location_key(forward_order), ((1, 5, 1), (10, 20, 1)))


class ImportGatesPocketOutputsTests(TestCase):
    def test_clean_normalizes_missing_markers(self):
        self.assertEqual(gates_clean(None), "")
        self.assertEqual(gates_clean("nan"), "")
        self.assertEqual(gates_clean("  1ABC  "), "1ABC")

    def test_is_pdb_code_requires_leading_digit_and_length_four(self):
        self.assertTrue(gates_is_pdb_code("1abc"))
        self.assertFalse(gates_is_pdb_code("abcd"))
        self.assertFalse(gates_is_pdb_code("1ab"))

    def test_parse_pdb_chain_source_extracts_code_and_chain(self):
        self.assertEqual(parse_pdb_chain_source("1ABC_CHAIN_A"), ("1ABC", "A"))
        self.assertEqual(parse_pdb_chain_source("PDB_1ABC_CHAIN_B"), ("1ABC", "B"))

    def test_parse_pdb_chain_source_returns_none_for_non_matching_value(self):
        self.assertIsNone(parse_pdb_chain_source("not-a-chain-source"))

    def test_is_no_pocket_matches_known_spellings(self):
        self.assertTrue(is_no_pocket("no_pockets"))
        self.assertTrue(is_no_pocket("NO POCKETS"))
        self.assertFalse(is_no_pocket("1ABC"))

    def test_selected_sources_reads_fpocket_and_p2rank_columns(self):
        row = {
            "best_fpocket_structure": "1ABC",
            "fpocket_pocket": "Pocket1",
            "best_p2rank_structure": "1ABC",
            "p2rank_pocket": "pocket1",
        }

        sources = selected_sources(row)

        self.assertEqual(
            sources,
            [
                {
                    "method": "fpocket",
                    "source": "1ABC",
                    "pocket": "Pocket1",
                    "residue_set": "FPocketPocket",
                },
                {
                    "method": "p2rank",
                    "source": "1ABC",
                    "pocket": "pocket1",
                    "residue_set": "P2RankPocket",
                },
            ],
        )

    def test_colabfold_sources_prefixes_locus_with_cb(self):
        row = {"colabfold_fpocket_pocket": "Pocket1", "colabfold_p2rank_pocket": "pocket1"}

        sources = colabfold_sources(row, "LOCUS1")

        self.assertEqual(sources[0]["source"], "CB_LOCUS1")
        self.assertEqual(sources[1]["source"], "CB_LOCUS1")


class SelectedPdbPocketReportTests(TestCase):
    def test_clean_normalizes_missing_markers(self):
        self.assertEqual(pdb_report_clean(None), "")
        self.assertEqual(pdb_report_clean("null"), "")

    def test_is_pdb_code_only_checks_length_and_alnum(self):
        # Unlike import_gates_pocket_outputs.is_pdb_code, this variant does
        # not require the code to start with a digit.
        self.assertTrue(pdb_report_is_pdb_code("ABCD"))
        self.assertTrue(pdb_report_is_pdb_code("1ABC"))
        self.assertFalse(pdb_report_is_pdb_code("AB"))

    def test_is_expected_no_pockets_only_applies_to_p2rank(self):
        self.assertTrue(_is_expected_no_pockets("P2Rank", "no_pockets"))
        self.assertFalse(_is_expected_no_pockets("FPocket", "no_pockets"))
        self.assertFalse(_is_expected_no_pockets("P2Rank", "some_pocket"))


class ExportSelectedAlphafoldPocketJobsTests(TestCase):
    def test_clean_normalizes_missing_markers(self):
        self.assertEqual(af_clean(None), "")
        self.assertEqual(af_clean("nan"), "")

    def test_norm_source_strips_known_prefixes(self):
        self.assertEqual(norm_source("AF_P12345"), "P12345")
        self.assertEqual(norm_source("CB_LOCUS1"), "LOCUS1")
        self.assertEqual(norm_source("P12345"), "P12345")

    def test_is_pdb_code_does_not_require_leading_digit(self):
        self.assertTrue(af_is_pdb_code("1ABC"))
        self.assertTrue(af_is_pdb_code("ABCD"))
        self.assertFalse(af_is_pdb_code("AB"))

    def test_is_alphafold_uniprot_source_accepts_af_and_uniprot_shaped_codes(self):
        self.assertTrue(is_alphafold_uniprot_source("AF_P12345"))
        self.assertTrue(is_alphafold_uniprot_source("A0A123456"))
        self.assertTrue(is_alphafold_uniprot_source("P12345"))

    def test_is_alphafold_uniprot_source_rejects_pdb_and_colabfold_codes(self):
        self.assertFalse(is_alphafold_uniprot_source("1ABC"))
        self.assertFalse(is_alphafold_uniprot_source("CB_LOCUS1"))
        self.assertFalse(is_alphafold_uniprot_source(""))

    def test_structure_code_uppercases_and_prefixes(self):
        self.assertEqual(structure_code("p12345"), "AF_P12345")

    def test_folder_path_splits_genome_accession_into_middle_bucket_directory(self):
        # Same bucket-math bug class documented in pipeline/tests -- the
        # InterProScan -b/-o mixup and a prior folder_path off-by-one both
        # came from guessing this arithmetic instead of reading it.
        self.assertEqual(
            af_folder_path("/app/tp/data", "NZ_AP023069.1"),
            "/app/tp/data/023/NZ_AP023069.1",
        )


class ExportSelectedPdbPocketJobsTests(TestCase):
    def test_clean_normalizes_missing_markers(self):
        self.assertEqual(pdb_export_clean(None), "")
        self.assertEqual(pdb_export_clean("null"), "")

    def test_is_pdb_code_requires_leading_digit(self):
        self.assertTrue(pdb_export_is_pdb_code("1abc"))
        self.assertFalse(pdb_export_is_pdb_code("abcd"))

    def test_folder_path_splits_genome_accession_into_middle_bucket_directory(self):
        self.assertEqual(
            pdb_export_folder_path("/app/tp/data", "NZ_AP023069.1"),
            "/app/tp/data/023/NZ_AP023069.1",
        )

    def test_parse_structure_candidates_reads_python_set_literal(self):
        candidates = _parse_structure_candidates("{'1ABC', '2XYZ'}")
        self.assertEqual(candidates, ["1ABC", "2XYZ"])

    def test_parse_structure_candidates_filters_out_non_pdb_codes(self):
        candidates = _parse_structure_candidates("{'1ABC', 'nothing'}")
        self.assertEqual(candidates, ["1ABC"])

    def test_parse_structure_candidates_falls_back_to_brace_stripping_on_bad_literal(self):
        # Not a valid Python literal (unquoted identifiers) -- ast.literal_eval
        # raises, so this exercises the comma-split fallback branch instead.
        candidates = _parse_structure_candidates("{1ABC, 2XYZ}")
        self.assertEqual(candidates, ["1ABC", "2XYZ"])

    def test_parse_structure_candidates_empty_value_returns_empty_list(self):
        self.assertEqual(_parse_structure_candidates(""), [])


class LoadCsaHelperTests(TestCase):
    def test_clean_optional_text_normalizes_missing_markers(self):
        self.assertEqual(_clean_optional_text(None), "")
        self.assertEqual(_clean_optional_text("  nan  "), "")
        self.assertEqual(_clean_optional_text("  Ser  "), "Ser")

    def test_clean_optional_text_uppercases_when_requested(self):
        self.assertEqual(_clean_optional_text("ser", upper=True), "SER")

    def test_parse_residue_identifier_handles_plain_integer(self):
        self.assertEqual(_parse_residue_identifier("42"), (42, ""))

    def test_parse_residue_identifier_handles_float_like_string(self):
        self.assertEqual(_parse_residue_identifier("42.0"), (42, ""))

    def test_parse_residue_identifier_handles_insertion_code(self):
        self.assertEqual(_parse_residue_identifier("42A"), (42, "A"))

    def test_parse_residue_identifier_handles_negative_number(self):
        self.assertEqual(_parse_residue_identifier("-5"), (-5, ""))

    def test_parse_residue_identifier_returns_none_for_missing_value(self):
        self.assertEqual(_parse_residue_identifier(None), (None, ""))

    def test_parse_residue_identifier_returns_none_for_unparsable_text(self):
        self.assertEqual(_parse_residue_identifier("not-a-number"), (None, ""))

    def test_site_storage_name_uses_bare_id_when_grouped_across_chains(self):
        self.assertEqual(_site_storage_name("SITE1", "A", True), "SITE1")

    def test_site_storage_name_includes_chain_when_not_grouped(self):
        self.assertEqual(_site_storage_name("SITE1", "A", False), "SITE1 | chain A")


class ImportCuratedUniprotHelperTests(TestCase):
    def test_parse_uniprot_accessions_whole_value_missing_marker_returns_empty(self):
        self.assertEqual(_parse_uniprot_accessions("NA"), [])

    def test_parse_uniprot_accessions_splits_on_comma_semicolon_and_whitespace(self):
        self.assertEqual(
            _parse_uniprot_accessions("P12345, P67890;P11111"),
            ["P12345", "P67890", "P11111"],
        )

    def test_parse_uniprot_accessions_strips_swissprot_pipe_format(self):
        self.assertEqual(_parse_uniprot_accessions("sp|P12345|GENE_HUMAN"), ["P12345"])

    def test_parse_uniprot_accessions_drops_missing_tokens_within_a_list(self):
        self.assertEqual(_parse_uniprot_accessions("P12345, NA, P67890"), ["P12345", "P67890"])

    def test_compute_folder_path_splits_genome_accession_into_middle_bucket_directory(self):
        self.assertEqual(
            curated_uniprot_folder_path("/app/tp/data", "NZ_AP023069.1"),
            "/app/tp/data/023/NZ_AP023069.1",
        )


class SelectedAlphafoldSourceReportIsLoadedTests(TestCase):
    def test_exact_af_prefixed_code_matches(self):
        self.assertTrue(is_loaded("P12345", ["AF_P12345"]))

    def test_bare_accession_code_matches(self):
        self.assertTrue(is_loaded("P12345", ["P12345"]))

    def test_chain_suffixed_af_code_matches(self):
        self.assertTrue(is_loaded("P12345", ["AF_P12345_CHAIN_A"]))

    def test_unrelated_code_does_not_match(self):
        self.assertFalse(is_loaded("P12345", ["AF_P99999"]))

    def test_no_loaded_codes_does_not_match(self):
        self.assertFalse(is_loaded("P12345", []))
