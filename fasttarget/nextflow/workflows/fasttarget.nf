#!/usr/bin/env nextflow

/*
========================================================================================
    FastTarget Nextflow Workflow
========================================================================================
    Main workflow that orchestrates all analysis modules
----------------------------------------------------------------------------------------
*/

nextflow.enable.dsl = 2

// Import all modules
include { GENOME_PREPARATION } from '../modules/genome_preparation'
include { METABOLISM_PATHWAYTOOLS } from '../modules/metabolism_pathwaytools'
include { METABOLISM_SBML } from '../modules/metabolism_sbml'
include { STRUCTURES_UNIPROT_MAPPING } from '../modules/structures_uniprot_mapping'
include { STRUCTURES_PREPARE; STRUCTURES_DOWNLOAD_SINGLE; STRUCTURES_EXTRACT_CHAINS_SINGLE; STRUCTURES_EXTRACT_CHAINS_COLLECT } from '../modules/structures_download'
include { COLABFOLD_SINGLE; COLABFOLD_COLLECT } from '../modules/structures_colabfold_single'
include { STRUCTURES_POCKETS_SINGLE; STRUCTURES_POCKETS_COLLECT } from '../modules/structures_pockets'
include { STRUCTURES_MERGE } from '../modules/structures_merge'
include { CONSERVATION_DOWNLOAD_GENOMES } from '../modules/conservation_download'
include { CONSERVATION_ROARY } from '../modules/conservation_roary'
include { CONSERVATION_CORECRUNCHER } from '../modules/conservation_corecruncher'
include { OFFTARGET_HUMAN } from '../modules/offtarget_human'
include { OFFTARGET_MICROBIOME } from '../modules/offtarget_microbiome'
include { OFFTARGET_FOLDSEEK } from '../modules/offtarget_foldseek'
include { ESSENTIALITY_DEG } from '../modules/essentiality_deg'
include { LOCALIZATION_PSORTB } from '../modules/localization_psortb'
include { METADATA_LOADING } from '../modules/metadata_loading'
include { MERGE_FINAL_RESULTS } from '../modules/merge_final_results'

/*
========================================================================================
    WORKFLOW: FASTTARGET
========================================================================================
*/

workflow FASTTARGET {
    take:
    config_file
    
    main:
    
    // Parse configuration file
    def config = parseConfig(config_file)
    
    // Extract common parameters
    organism_name = config.organism.name
    gbk_file = file(config.organism.gbk_file)
    tax_id = config.organism.tax_id
    strain_taxid = config.organism.strain_taxid
    
    output_path = params.output_path \
        ? file(params.output_path).toAbsolutePath().toString() \
        : file("${workflow.projectDir}/../organism").toAbsolutePath().toString()
    databases_path = params.databases_path \
        ? file(params.databases_path).toAbsolutePath().toString() \
        : file("${workflow.projectDir}/../databases").toAbsolutePath().toString()
    cpus = config.cpus ?: Runtime.runtime.availableProcessors()
    container_engine = config.container_engine ?: 'docker'
    
    log.info """
    ================================================================================
    F A S T T A R G E T   P I P E L I N E
    ================================================================================
    Organism        : ${organism_name}
    Output path     : ${output_path}
    Databases path  : ${databases_path}
    CPUs            : ${cpus}
    Container engine: ${container_engine}
    ================================================================================
    """.stripIndent()
    
    // ============================================================================
    // STEP 1: GENOME PREPARATION (Required - always runs)
    // ============================================================================
    
    GENOME_PREPARATION(
        gbk_file,
        organism_name,
        output_path,
        container_engine
    )
    
    // ============================================================================
    // STEP 2: METABOLIC ANALYSIS (Conditional)
    // ============================================================================
    
    // PathwayTools analysis (if enabled)
    def ptools_enabled = config.'metabolism-PathwayTools'?.enabled ?: false
    if (ptools_enabled) {
        def curated_ubiq = config.'metabolism-PathwayTools'.curated_ubiquitous_file
        def curated_ubiq_file = (curated_ubiq && curated_ubiq != 'None' && curated_ubiq != '') ? file(curated_ubiq) : file('NO_FILE')
        
        METABOLISM_PATHWAYTOOLS(
            organism_name,
            output_path,
            GENOME_PREPARATION.out.gbk,
            file(config.'metabolism-PathwayTools'.sbml_file),
            file(config.'metabolism-PathwayTools'.chokepoint_file),
            file(config.'metabolism-PathwayTools'.smarttable_file),
            curated_ubiq_file
        )
    }
    
    // SBML/MetaGraphTools analysis (if enabled)
    def sbml_enabled = config.'metabolism-SBML'?.enabled ?: false
    if (sbml_enabled) {
        METABOLISM_SBML(
            organism_name,
            output_path,
            GENOME_PREPARATION.out.gbk,
            file(config.'metabolism-SBML'.sbml_file),
            file(config.'metabolism-SBML'.filter_file),
            container_engine
        )
    }
    // ============================================================================
    // STEP 3: STRUCTURE ANALYSIS (Conditional)
    // ============================================================================
    
    def structures_enabled = config.structures?.enabled ?: false
    def resolution_cutoff = config.structures?.resolution_cutoff ?: 3.5
    def coverage_cutoff = config.structures?.coverage_cutoff ?: 40.0
    def pocket_full_mode = config.structures?.pocket_full_mode ?: false
    def colabfold_enabled = structures_enabled && (config.colabfold?.enabled ?: false)
    def colabfold_amber = config.colabfold?.amber ?: false
    def colabfold_gpu = config.colabfold?.gpu ?: false
    def colabfold_all_models = config.colabfold?.colabfold_run_all ?: false
    
    if (structures_enabled) {
        // 3.1: UniProt mapping
        STRUCTURES_UNIPROT_MAPPING(
            organism_name,
            output_path,
            tax_id,
            strain_taxid,
            cpus,
            GENOME_PREPARATION.out.faa,
            GENOME_PREPARATION.out.gbk
        )
        
        // 3.2: Prepare structures and get locus tag list
        STRUCTURES_PREPARE(
            organism_name,
            output_path,
            STRUCTURES_UNIPROT_MAPPING.out.uniprot_dir,
            GENOME_PREPARATION.out.gbk,
            resolution_cutoff,
            coverage_cutoff
        )
        
        // Split locus tags and download in parallel
        STRUCTURES_PREPARE.out.locus_tags_list
            .splitText()
            .map { it.trim() }
            .filter { it.length() > 0 }  // Remove empty lines
            .set { locus_tags_channel }
        
        // Pair each locus tag with the staged structures directory so
        // STRUCTURES_DOWNLOAD_SINGLE runs as one task per locus in parallel.
        locus_tags_channel
            .combine(STRUCTURES_PREPARE.out.structure_dir.first())
            .map { locus_tag, structures_dir -> tuple(locus_tag, structures_dir) }
            .set { locus_tags_for_downloads }

        STRUCTURES_DOWNLOAD_SINGLE(
            locus_tags_for_downloads
        )
        
        STRUCTURES_DOWNLOAD_SINGLE.out.locus_download_pair
            .combine(STRUCTURES_PREPARE.out.structure_dir.first())
            .map { locus_tag, download_dir, structures_dir -> tuple(locus_tag, download_dir, structures_dir) }
            .set { locus_tags_for_chain_extraction }

        STRUCTURES_EXTRACT_CHAINS_SINGLE(
            locus_tags_for_chain_extraction,
            organism_name,
            pocket_full_mode
        )

        STRUCTURES_EXTRACT_CHAINS_COLLECT(
            organism_name,
            output_path,
            STRUCTURES_PREPARE.out.structure_dir.first(),
            STRUCTURES_EXTRACT_CHAINS_SINGLE.out.locus_structure_dir.collect().ifEmpty([])
        )

        if (colabfold_enabled) {
            // 3.2b: ColabFold parallelized per protein (GPU tasks in parallel)
            // Create channel with locus_tags and their structure dirs
            STRUCTURES_PREPARE.out.locus_tags_list
                .splitText()
                .map { it.trim() }
                .filter { it.length() > 0 }
                .combine(STRUCTURES_EXTRACT_CHAINS_COLLECT.out.structure_dir)
                .map { locus_tag, structures_dir -> tuple(locus_tag, file("${structures_dir}/${locus_tag}")) }
                .set { locus_tags_for_colabfold }

            COLABFOLD_SINGLE(
                locus_tags_for_colabfold,
                organism_name,
                output_path,
                GENOME_PREPARATION.out.gbk,
                colabfold_amber,
                colabfold_gpu,
                colabfold_all_models
            )

            COLABFOLD_COLLECT(
                organism_name,
                output_path,
                STRUCTURES_EXTRACT_CHAINS_COLLECT.out.structure_dir,
                COLABFOLD_SINGLE.out.colabfold_cb_results
                    .map { locus_tag, cb_file -> [locus_tag, cb_file.toString()] }
                    .collect()
                    .ifEmpty([]),
                COLABFOLD_SINGLE.out.colabfold_models_results
                    .map { locus_tag, models_dir -> [locus_tag, models_dir.toString()] }
                    .collect()
                    .ifEmpty([]),
                COLABFOLD_SINGLE.out.colabfold_summary_results
                    .map { locus_tag, summary_file -> [locus_tag, summary_file.toString()] }
                    .collect()
                    .ifEmpty([])
            )
        }

        // 3.3: Pocket detection (parallelized per locus)
        // Use explicit upstream structures directory instead of published output path
        def pockets_structures_dir = colabfold_enabled ? COLABFOLD_COLLECT.out.structure_dir : STRUCTURES_EXTRACT_CHAINS_COLLECT.out.structure_dir
        STRUCTURES_PREPARE.out.locus_tags_list
            .splitText()
            .map { it.trim() }
            .filter { it.length() > 0 }  // Remove empty lines
            .combine(pockets_structures_dir)
            .map { locus_tag, structures_dir -> tuple(locus_tag, structures_dir) }
            .set { locus_tags_for_pockets }
        
        STRUCTURES_POCKETS_SINGLE(
            locus_tags_for_pockets,
            output_path,
            organism_name,
            container_engine,
            pocket_full_mode,
            colabfold_enabled,
            colabfold_all_models,
            resolution_cutoff,
            coverage_cutoff
        )
        
        STRUCTURES_POCKETS_COLLECT(
            organism_name,
            output_path,
            STRUCTURES_POCKETS_SINGLE.out.completed_tag.collect()
        )
        
        // 3.4: Merge structure data (waits for pockets to complete)
        def merge_structures_dir = colabfold_enabled ? COLABFOLD_COLLECT.out.structure_dir : STRUCTURES_EXTRACT_CHAINS_COLLECT.out.structure_dir
        STRUCTURES_MERGE(
            GENOME_PREPARATION.out.all_genome_files,
            merge_structures_dir,
            STRUCTURES_POCKETS_SINGLE.out.locus_pockets_dir
                .map { locus_tag, pockets_dir -> [locus_tag, pockets_dir.toString()] }
                .collect()
                .ifEmpty([]),
            organism_name,
            output_path,
            pocket_full_mode,
            colabfold_enabled,
            colabfold_all_models
        )
    }
    // ============================================================================
    // STEP 4: CONSERVATION ANALYSIS (Conditional)
    // ============================================================================
    
    def core_enabled = config.core?.enabled ?: false
    def roary_enabled = config.core?.roary ?: false
    def corecruncher_enabled = config.core?.corecruncher ?: false
    
    if (core_enabled && (roary_enabled || corecruncher_enabled)) {
        // 4.1: Download genomes
        def min_identity = config.core.min_identity ?: 95
        def min_core_freq = config.core.min_core_freq ?: 99
        def accession_file_path = config.core.accession_file ?: 'null'
        def accession_file = (accession_file_path && accession_file_path != 'null' && accession_file_path != '') ? file(accession_file_path) : file('NO_FILE')
        
        CONSERVATION_DOWNLOAD_GENOMES(
            organism_name,
            output_path,
            tax_id,
            container_engine,
            GENOME_PREPARATION.out.all_genome_files,
            accession_file
        )

        
        if (roary_enabled) {
            CONSERVATION_ROARY(
                organism_name,
                output_path,
                CONSERVATION_DOWNLOAD_GENOMES.out.gff_dir,
                GENOME_PREPARATION.out.all_genome_files,
                min_core_freq,
                min_identity,
                cpus,
                container_engine
            )
        }
        
        if (corecruncher_enabled) {
            CONSERVATION_CORECRUNCHER(
                organism_name,
                output_path,
                CONSERVATION_DOWNLOAD_GENOMES.out.faa_dir,
                GENOME_PREPARATION.out.all_genome_files,
                min_core_freq,
                min_identity,
                cpus,
                container_engine
            )
        }
    }
    
    // ============================================================================
    // STEP 5: OFFTARGET ANALYSIS (Conditional)
    // ============================================================================
    
    def offtarget_enabled = config.offtarget?.enabled ?: false
    def human_enabled = config.offtarget?.human ?: false
    def microbiome_enabled = config.offtarget?.microbiome ?: false
    def foldseek_enabled = config.offtarget?.foldseek_human ?: false
    
    // Human offtarget
    if (offtarget_enabled && human_enabled) {
        OFFTARGET_HUMAN(
            GENOME_PREPARATION.out.all_genome_files,
            organism_name,
            output_path,
            databases_path,
            cpus
        )
    }
    
    // Microbiome offtarget
    if (offtarget_enabled && microbiome_enabled) {
        def microbiome_identity = config.offtarget.microbiome_identity_filter ?: 40
        def microbiome_coverage = config.offtarget.microbiome_coverage_filter ?: 70
        
        OFFTARGET_MICROBIOME(
            GENOME_PREPARATION.out.all_genome_files,
            organism_name,
            output_path,
            databases_path,
            microbiome_identity,
            microbiome_coverage,
            cpus
        )
    }
    
    // Foldseek structural offtarget (requires structures enabled)
    if (offtarget_enabled && foldseek_enabled && structures_enabled) {
        // Use staged structures directory from upstream process output
        def foldseek_structures_dir = colabfold_enabled ? STRUCTURES_COLABFOLD.out.structure_dir : STRUCTURES_EXTRACT_CHAINS_COLLECT.out.structure_dir
        
        OFFTARGET_FOLDSEEK(
            GENOME_PREPARATION.out.all_genome_files,
            foldseek_structures_dir,
            organism_name,
            output_path,
            databases_path,
            container_engine,
            colabfold_all_models
        )
    }
    
    // ============================================================================
    // STEP 6: ESSENTIALITY ANALYSIS (Conditional)
    // ============================================================================
    
    def deg_enabled = config.deg?.enabled ?: false
    if (deg_enabled) {
        def deg_identity = config.deg.deg_identity_filter ?: 40
        def deg_coverage = config.deg.deg_coverage_filter ?: 70
        
        ESSENTIALITY_DEG(
            GENOME_PREPARATION.out.all_genome_files,
            organism_name,
            output_path,
            databases_path,
            deg_identity,
            deg_coverage,
            cpus
        )
    }
    
    // ============================================================================
    // STEP 7: LOCALIZATION ANALYSIS (Conditional)
    // ============================================================================
    
    def psortb_enabled = config.psortb?.enabled ?: false
    if (psortb_enabled) {
        def gram_type = config.psortb.gram_type ?: 'n'
        
        LOCALIZATION_PSORTB(
            GENOME_PREPARATION.out.all_genome_files,
            organism_name,
            output_path,
            gram_type,
            container_engine
        )
    }
    
    // ============================================================================
    // STEP 8: METADATA LOADING (Conditional)
    // ============================================================================
    
    def metadata_enabled = config.metadata?.enabled ?: false
    if (metadata_enabled) {
        // Convert metadata file list to channel
        def meta_files = config.metadata?.meta_tables ?: []
        Channel.fromPath(meta_files).collect().set { metadata_files_ch }
        
        METADATA_LOADING(
            organism_name,
            output_path,
            metadata_files_ch
        )
    }
    
    // ============================================================================
    // STEP 9: MERGE RESULTS (Always runs after all enabled modules)
    // ============================================================================
    
    // Build table channel from upstream process outputs (avoid reading published output tree)
    def merge_tables_ch = Channel.empty()
    
    if (ptools_enabled) {
        merge_tables_ch = merge_tables_ch
            .mix(METABOLISM_PATHWAYTOOLS.out.centrality)
            .mix(METABOLISM_PATHWAYTOOLS.out.producing)
            .mix(METABOLISM_PATHWAYTOOLS.out.consuming)
            .mix(METABOLISM_PATHWAYTOOLS.out.both)
            .mix(METABOLISM_PATHWAYTOOLS.out.edges)
    }
    if (sbml_enabled) {
        merge_tables_ch = merge_tables_ch
            .mix(METABOLISM_SBML.out.centrality)
            .mix(METABOLISM_SBML.out.producing)
            .mix(METABOLISM_SBML.out.consuming)
            .mix(METABOLISM_SBML.out.edges)
    }
    if (structures_enabled) {
        merge_tables_ch = merge_tables_ch.mix(STRUCTURES_MERGE.out.final_table)
    }
    if (core_enabled && roary_enabled) {
        merge_tables_ch = merge_tables_ch.mix(CONSERVATION_ROARY.out.core_table)
    }
    if (core_enabled && corecruncher_enabled) {
        merge_tables_ch = merge_tables_ch.mix(CONSERVATION_CORECRUNCHER.out.core_table)
    }
    if (offtarget_enabled && human_enabled) {
        merge_tables_ch = merge_tables_ch.mix(OFFTARGET_HUMAN.out.parsed_table)
    }
    if (offtarget_enabled && microbiome_enabled) {
        merge_tables_ch = merge_tables_ch
            .mix(OFFTARGET_MICROBIOME.out.counts_table)
            .mix(OFFTARGET_MICROBIOME.out.normalized_table)
            .mix(OFFTARGET_MICROBIOME.out.genomes_analyzed)
    }
    if (offtarget_enabled && foldseek_enabled && structures_enabled) {
        merge_tables_ch = merge_tables_ch.mix(OFFTARGET_FOLDSEEK.out.foldseek_table)
        merge_tables_ch = merge_tables_ch.mix(OFFTARGET_FOLDSEEK.out.foldseek_colab_table)
    }
    if (deg_enabled) {
        merge_tables_ch = merge_tables_ch.mix(ESSENTIALITY_DEG.out.deg_table)
    }
    if (psortb_enabled) {
        merge_tables_ch = merge_tables_ch.mix(LOCALIZATION_PSORTB.out.localization_table)
    }
    if (metadata_enabled) {
        merge_tables_ch = merge_tables_ch.mix(METADATA_LOADING.out.metadata_copies)
    }

    // Collect staged tables and run final merge once
    MERGE_FINAL_RESULTS(
        organism_name,
        output_path,
        GENOME_PREPARATION.out.gbk.first(),
        merge_tables_ch.collect().ifEmpty([])
    )
    
    emit:
    results = MERGE_FINAL_RESULTS.out.final_table
}

/*
========================================================================================
    HELPER FUNCTIONS
========================================================================================
*/

def parseConfig(configFile) {
    // Parse YAML configuration file
    def yaml = new org.yaml.snakeyaml.Yaml()
    def config = yaml.load(new File(configFile.toString()).text)
    return config
}

/*
========================================================================================
    COMPLETION HANDLER
========================================================================================
*/

workflow.onComplete {
    log.info """
    ================================================================================
    Pipeline completed!
    ================================================================================
    Status      : ${workflow.success ? 'SUCCESS' : 'FAILED'}
    Duration    : ${workflow.duration}
    Work dir    : ${workflow.workDir}
    ================================================================================
    """.stripIndent()
}
