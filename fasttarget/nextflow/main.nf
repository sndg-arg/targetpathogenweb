#!/usr/bin/env nextflow

/*
 * FastTarget - Nextflow Pipeline
 * ===============================
 * Drug target identification pipeline
 */

nextflow.enable.dsl = 2

// Print help message
def helpMessage() {
    log.info"""
    =========================================
    FastTarget - Nextflow Pipeline v${manifest.version}
    =========================================
    
    Usage:
    nextflow run main.nf --config_file config.yml [options]
    
    Required arguments:
      --config_file         Path to YAML configuration file (default: config.yml)
    
    Optional arguments:
      --databases_path      Path to databases directory (default: ../databases)
      --output_path         Path to output directory (default: ../organism)
      --max_cpus            Maximum number of CPUs (default: 4)
      --max_memory          Maximum memory (default: 8.GB)
      
    Profiles:
      -profile docker       Run with Docker containers
      -profile singularity  Run with Singularity containers
      -profile slurm        Run on SLURM cluster
      -profile sge          Run on SGE cluster
      -profile pbs          Run on PBS cluster
      
    Example:
      nextflow run main.nf --config_file config.yml -profile slurm
    
    """.stripIndent()
}

// Show help message
if (params.help) {
    helpMessage()
    exit 0
}

// Validate required parameters
if (!params.config_file) {
    log.error "ERROR: --config_file is required"
    exit 1
}

// Import workflows
include { FASTTARGET } from './workflows/fasttarget.nf'

// Main workflow
workflow {
    // Parse config file
    config_file = file(params.config_file)
    
    if (!config_file.exists()) {
        error "Configuration file not found: ${params.config_file}"
    }
    
    // Run main FastTarget workflow
    FASTTARGET(
        config_file
    )
}

workflow.onComplete {
    log.info ""
    log.info "Pipeline completed at: $workflow.complete"
    log.info "Execution status: ${ workflow.success ? 'SUCCESS' : 'FAILED' }"
    log.info "Execution duration: $workflow.duration"
    log.info ""
}
