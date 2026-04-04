## Prompt Optimization Suggestions

A **Prompt** is the textual instruction that users provide to an AI model—the primary way humans communicate with the AI. Well-crafted Prompts are essential for reliable workflow execution and successful outcomes.

Drawing from our hands-on experience debugging the BioGAIP project, we’ve compiled the following practical recommendations to help users achieve the best results with minimal interaction.

### The First Prompt Is Critical

BioGAIP is engineered to automate tasks with as few user interventions as possible. Consequently, the **initial Prompt** has an outsized impact on overall success. In our testing, a well-designed First Prompt enables more than 60% of tasks to complete automatically.

A strong Prompt should clearly include:
- Task overview
- Desired output / success criteria
- Target output directory (matching the paths configured in BioGAIP)
- Any additional context (data sources, reference genome version, etc.)

#### Recommended Principles

1. **Be Clear and Specific**  
   Explicitly state requirements and expectations—avoid ambiguity.

   **Good example:**
   ```markdown
   You are an experienced bioinformatician. Now process the WGS sequencing data from cell lines according to the following requirements. Strictly follow these steps exactly; do not add, omit, or assume any extra steps, tools, or paths.

   1. Perform necessary quality control and preprocessing on the sequencing data.
   2. Align the sequencing data to the reference genome using bwa.
   3. Perform quality control and processing on the mapped BAM files (e.g., duplicate removal).
   ...
   ```

   **Bad example:**
   ```markdown
   Please Process WGS Sequencing data store at: /path/to/input and output to /path/to/output
   ```

2. **Filename Is Also a Prompt**  
   For the Agent, a Prompt is not limited to what you type—file naming conventions act as powerful *implicit* context.  
   Data from sequencing vendors or public repositories often have cryptic names. We strongly recommend renaming files to convey clear biological meaning:

| Original Filename (no sample info inferable) | Group      | Replicate | Recommended Name `{group_name}_{rep_id}_{reads_id}.fq.gz` |
|----------------------------------------------|------------|-----------|-----------------------------------------------------------|
| 202202001H1_Line001_clean_r1.fq.gz                         | DHX48 KO | 1    | DHX48_KO_rep1_r1.fq.gz                               |
| 202202001H1_Line001_ clean_r2.fq.gz                        | DHX48 KO | 1    | DHX48_KO_rep1_r2.fq.gz                               |
| 202202001H2_Line001_clean_r1.fq.gz                         | DHX48 KO | 2    | DHX48_KO_rep2_r1.fq.gz                               |
| 202202001H2_Line001_clean_r2.fq.gz                         | DHX48 KO | 2    | DHX48_KO_rep2_r2.fq.gz                               |
| 202202001H3_Line001_clean_r1.fq.gz                         | DHX48 KO | 3    | DHX48_KO_rep3_r1.fq.gz                               |
| 202202001H3_Line001_clean_r2.fq.gz                         | DHX48 KO | 3    | DHX48_KO_rep3_r2.fq.gz                               |
| 202202001H4_Line001_clean_r1.fq.gz                         | Control  | 1    | Control_rep1_r1.fq.gz                                |
| 202202001H4_Line001_clean_r2.fq.gz                         | Control  | 1    | Control_rep1_r2.fq.gz                                |
| 202202001H5_Line001_clean_r1.fq.gz                         | Control  | 2    | Control_rep2_r1.fq.gz                                |
| 202202001H5_Line001_clean_r2.fq.gz                         | Control  | 2    | Control_rep2_r2.fq.gz                                |
| 202202001H6_Line001_clean_r1.fq.gz                         | Control  | 3    | Control_rep3_r1.fq.gz                                |
| 202202001H6_Line001_clean_r2.fq.gz                         | Control  | 3    | Control_rep3_r2.fq.gz                                |


3. **Avoid Errors**  
   Many large models will not proactively correct user mistakes, rapidly consuming context. Common pitfalls we’ve observed:
   - Using paths without write permissions (check BioWorker configuration)
   - Specifying incorrect tools or parameters (e.g., STAR for WGS data, or non-existent flags)

4. **Intervene Promptly**  
   If serious errors or hallucinations appear within the first few rounds after the First Prompt, automatic recovery is unlikely. Use the UI’s **Interrupt** or **Summarize** feature immediately to reset and guide the Agent.

5. **Repetition Is the Best Antidote to Hallucinations (Advanced Users)**  
   Despite built-in safeguards, hallucinations can still occur. For stubborn cases:
   - Repeat the First Prompt verbatim at the very beginning of the task (twice is often sufficient).
   - Advanced users can configure custom Agents (via BioAG’s custom interface) to inject the First Prompt into every Planner round.

### Try Before You Run

We highly recommend performing a small-scale experimental run
 with the same analysis goals before executing your full production task. 

For example, if you plan to analyze an RNA-seq dataset containing 300 control samples and 300 experimental samples, we suggest setting up a smaller evaluation dataset first. 

In this scenario, you could select a subset of 10 vs. 10 samples to test the effectiveness of your prompt. If the results meet your expectations, you can confidently proceed with the full-scale analysis. If not, you can easily tweak and optimize your prompt beforehand.

### Examples

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