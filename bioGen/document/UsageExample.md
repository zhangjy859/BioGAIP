#### Bulk RNA-seq
```markdown
You are an expert bioinformatician tasked with processing RNA-seq sequencing data from the dataset GSE281525. The data is stored in the directory <input directory, e.g., /mnt/data1/BioGAIP_test/input>, which includes RNA-seq data for xxx and xxx. Please download the human reference genome <reference genome version, e.g., hg38> and its corresponding GTF annotation file from GENCODE or UCSC and save to <output directory, e.g., /mnt/data1/BioGAIP_test/reference>.

Perform the following pipeline steps on the data:

Conduct quality control (QC) using appropriate tools such as FastQC or MultiQC.
Align the reads to the <reference genome version, e.g., hg38> reference genome using STAR.
Quantify transcripts using featureCounts.
Perform differential expression analysis using DESeq2 to identify genes with differential expression between xxxx and xxx tumor samples.

All outputs must be saved in <output directory, e.g., /mnt/data1/BioGAIP_test/output>. If you need to create or manage environments (e.g., Conda envs), store them in <env directory, e.g., /mnt/data1/BioGAIP_test/envs>.
You have access to <cpu number> CPU cores for parallel processing where applicable.
Expected Outputs:

1. Aligned BAM files for each sample.
2. Transcript quantification results (e.g., count matrices).
3. A list of differentially expressed genes, including fold changes, p-values, and adjusted p-values.

Note: You only have write permissions to the output folder and the conda folder.
```

#### WGS
```markdown
You are an experienced bioinformatician. Now process the WGS sequencing data from cell lines according to the following requirements. Strictly follow these steps exactly; do not add, omit, or assume any extra steps, tools, or paths.

1. Perform necessary quality control and preprocessing on the sequencing data.
2. Align the sequencing data to the reference genome using bwa.
3. Perform quality control and processing on the mapped BAM files (e.g., duplicate removal).
4. Use GATK to perform variant analysis for each sample and merge all analysis results.
5. Perform quality control on the variant analysis results.
6. Retain all necessary intermediate results and logs.

Input sequencing data location: <input directory>
Reference genome location: <reference genome>
Output directory: <output directory>
Conda environment: <env directory> (use only if needed; prefer pre-installed packages).

You have total <cpu number> CPU cores to use.

Note: You only have write permissions to the output folder and the conda folder.
```

#### GEO Reanalysis
```markdown
You are a bioinformatics expert tasked with analyzing the GEO public dataset GSE60052, which contains RNA-seq data from 79 small cell lung cancer (SCLC) samples and 7 normal control samples. SCLC is a tumor with complex pathogenesis and poor prognosis. Follow these steps precisely, using verified tools and data sources to avoid hallucinations or assumptions. Base all actions on factual data retrieved from reliable databases, and document your reasoning step by step.

1. Access the GEO database via appropriate tools to retrieve and summarize relevant information for the accession number GSE60052, including dataset description. Do not assume any details; verify everything from the source.
2. Directly download the gene expression data from the GEO database web page if needed (use wget or other tools). Analyze its content and structure, including file format, sample groups, and any preprocessing notes. Output a clear summary of the findings.
3. Use the limma R package to perform differential expression analysis. Identify differentially expressed genes between the tumor samples (SCLC) and the paired/control samples (normal). Apply standard statistical methods: normalize data, fit models, and use adjusted p-values (e.g., FDR < 0.05) for significance. Explain your code and results step by step, without fabricating data.

Save all outputs, including files, logs, and results, in <output directory>. If creating or managing environments (e.g., Conda envs), store them in <env directory>.

Proceed step by step, and only use tools or code that directly support the tasks. If any information is unclear or inaccessible, note it explicitly without guessing.
```

#### ATAC Seq
```
You are an expert in ATAC-seq data analysis.  
The raw ATAC-seq FASTQ files for FOXA2+ and FOXA2- PDX tumor samples are stored in:  
<input directory>
File naming convention:  
<Insert your file naming rules here> 
Example: <file name example>
Reference genome directory: <reference genome directory>
ATAC-seq blacklist directory: `<atac blacklist directory>`

Please perform the following analysis steps:  
1. Quality control of raw reads and align clean reads to the hg38 reference genome.  
2. Merge technical replicates into biological replicates.  
3. Call consensus peaks between the two biological replicates for each sample.  
4. Generate separate consensus peak sets for FOXA2+ samples and FOXA2- samples.  
5. Identify differential accessible peaks between FOXA2+ and FOXA2- groups.  
6. Keep all necessary intermediate files.  

All output files must be saved in:  
`<output directory> `  

If a conda environment is needed, create and save it in:  
`<env directory> `  
You are only allowed to write to the above output directory and environment directory.
You have total <core number> CPU cores to use, please try to fully use all CPU resource.

```