# Define starters similar to Chainlit's set_starters
starters = [
    {
        "label": "RNA-seq",
        "message": """Objective: Perform RNA-Seq analysis, including transcript abundance quantification and differential expression analysis (DEA), using STAR for alignment and featureCounts for quantification. Store results in /RNA-seq.
Expected Outputs:
Aligned BAM files with corresponding indices.
Transcript abundance counts.
Differential Expression Analysis (DEA) using DESeq2, performed if grouping information is provided or can be inferred from FASTQ file names.
User Input Requirements:Please provide the following details to proceed with the analysis:
FASTQ File Location:
Specify the directory path containing your RNA-Seq FASTQ files.
Reference Genome and Annotation:
Reference Genome (FASTA format): Provide the full path to the reference genome FASTA file.
Annotation File (GTF/GFF3 format): Provide the full path to the gene annotation file.
Optional: If needed, download resources from Ensembl or UCSC Genome Browser. For example, use wget to retrieve files like Homo_sapiens.GRCh38.dna.primary_assembly.fa.gz or Homo_sapiens.GRCh38.108.gtf.gz from Ensembl.
Grouping Information for DEA:
Provide Grouping Information: Submit experimental group details (e.g., 'control', 'treatment') in a comma-separated list or table linking each FASTQ file to a group.
Infer from FASTQ File Names: If group information can be derived from FASTQ file names (e.g., sample1_control_R1.fastq.gz, sample2_treatment_R1.fastq.gz), describe the naming convention.
Optional Parameters:
Number of Threads: Specify the number of CPU threads available to optimize processing speed.
Instructions:
ASK USER the requested information to initiate the analysis.
After receiving the inputs, the system will summarize the provided details, perform the analysis, and store results in /RNA-seq.
Upon completion, confirm with the user if additional tasks are needed.
""",
        "icon": "http://nondisk.136138189.xyz:2086/f/aOi6/ngs.png",
    },
    {
        "label": "WGS analysis",
        "message": """Objective: Perform Whole Genome Sequencing (WGS) analysis, including read alignment, variant calling, and variant annotation. Use BWA for alignment, GATK for variant calling, and ANNOVAR or similar for annotation. Store results in /WGS.
Expected Outputs:
Aligned BAM files with indices.
Variant Call Format (VCF) files containing single nucleotide variants (SNVs) and indels.
Annotated variants with functional predictions.
User Input Requirements: Please provide the following details to proceed with the analysis:
FASTQ File Location:
Specify the directory path containing your WGS FASTQ files.
Reference Genome:
Reference Genome (FASTA format): Provide the full path to the reference genome FASTA file.
Optional: Download from Ensembl or UCSC, e.g., Homo_sapiens.GRCh38.dna.primary_assembly.fa.gz.
Known Variants (optional for recalibration):
Provide paths to known variant sites (e.g., dbSNP, Mills indels) if available.
Optional Parameters:
Number of Threads: Specify CPU threads for faster processing.
Instructions:
ASK USER the requested information to start the analysis.
The system will summarize inputs, execute the pipeline, and store results in /WGS.
Upon completion, ask if further analysis is required.
""",
        "icon": "http://nondisk.136138189.xyz:2086/f/4Vcj/wgs.png",
    },
    {
        "label": "ATAC-seq",
        "message": """Objective: Perform ATAC-Seq analysis to assess chromatin accessibility, including read alignment, peak calling, and differential accessibility analysis. Use Bowtie2 for alignment and MACS2 for peak calling. Store results in /ATAC-seq.
Expected Outputs:
Aligned BAM files with indices.
Peak files in BED or narrowPeak format.
Differential accessibility results if grouping is provided.
User Input Requirements: Please provide the following details to proceed with the analysis:
FASTQ File Location:
Specify the directory path containing your ATAC-Seq FASTQ files.
Reference Genome:
Reference Genome (FASTA format): Provide the full path to the reference genome FASTA file.
Optional: Download from Ensembl or UCSC, e.g., Homo_sapiens.GRCh38.dna.primary_assembly.fa.gz.
Grouping Information (for differential analysis):
Provide group details (e.g., 'control', 'treatment') linked to FASTQ files, or describe naming convention for inference.
Optional Parameters:
Number of Threads: Specify CPU threads for optimization.
Instructions:
ASK USER the requested information to initiate the analysis.
The system will summarize inputs, perform the analysis, and store results in /ATAC-seq.
Upon completion, confirm if additional tasks are needed.
""",
        "icon": "http://nondisk.136138189.xyz:2086/f/8whM/Transposase_ATAC.svg",
    },
]

agent_avatars = {
    "user": "🧑",
    "user_proxy": "👤",
    "system_check_agent": "🔍",
    "bio_micromamba_env_agent": "🧪",
    "file_agent": "📁",
    "web_surfer_agent": "🌐",
    "manager_mem_agent": "🧠",
    "system": "⚙️",
    "planning_agent": "🗂️",
    "query_agent": "❓",
    "command_generator_agent": "💻",
    "code_generator_agent": "📝",
    "safety_checker_agent": "🛡️",
    "executor_agent": "🚀",
    "assistant": "🤖",
}