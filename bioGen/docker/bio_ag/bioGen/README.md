<p align="center">
  <img src="http://nondisk.136138189.xyz:2086/f/Aq5SV/bioGAIP%20Logo.png" alt="BioGAIP Logo" width="300"/>
</p>

<h1 align="center">BioGAIP</h1>
<h3 align="center">AI-Powered Bioinformatics Agent • Turn Natural Language into End-to-end Pipelines</h3>

<p align="center">
  <a href="https://github.com/zhangjy859/BioGAIP/stargazers"><img src="https://img.shields.io/github/stars/zhangjy859/BioGAIP?style=for-the-badge&color=0A66C2" alt="Stars"/></a>
  <a href="https://github.com/zhangjy859/BioGAIP/releases"><img src="https://img.shields.io/github/v/release/zhangjy859/BioGAIP?style=for-the-badge&color=00C853" alt="Version 1.30"/></a>
  <a href="LICENSE"><img src="https://img.shields.io/github/license/zhangjy859/BioGAIP?style=for-the-badge&color=FF6D00" alt="AGPL-3.0"/></a>
  <a href="https://github.com/zhangjy859/BioGAIP/issues"><img src="https://img.shields.io/github/issues/zhangjy859/BioGAIP?style=for-the-badge&color=EA4335" alt="Issues"/></a>
</p>
<p align="center">
  <strong>No scripting. No conda hell. No 3-day debugging.</strong><br>
  Just update your data (to your server) and describe your analysis Natural Language — the AI builds runs, and debug the entire pipeline.
</p>


<p align="center">
  <a href="quickstart.md"><strong>Quick Start →</strong></a>
  &nbsp;&nbsp;•&nbsp;&nbsp;
  <a href="#✨-why-biogaip">Features</a>
  &nbsp;&nbsp;•&nbsp;&nbsp;
  <a href="#🎯-tested-analyses">Supported Analyses</a>
  &nbsp;&nbsp;•&nbsp;&nbsp;
  <a href="📚-full-documentation">Full Guidelines</a>
</p>

---

## ✨ Why BioGAIP

| Feature                    | Traditional Way            | BioGAIP                                   |
| -------------------------- | -------------------------- | ----------------------------------------- |
| **Workflow Creation**      | Write Many lines of Bash/R | Some natural-language paragraph           |
| **Environment Management** | Manual conda/docker        | Fully automatic                           |
| **Data Security**          | -     | Premise (your server and you choosed LLM) |
| **Learning Curve**         | Weeks                      | Hours                                     |

**Result**: From raw FASTQ (RNA-seq) to publication-ready results in hours.

## 🚀 Key Features

Compared to existing solutions, BioGAIP stands out with several distinct advantages:

- **Intuitive User Experience**: We've designed user-friendly interfaces for nearly every scenario—from initial deployment to daily application—ensuring effortless operation for users of all skill levels.
- **Cross-Platform Compatibility**: Powered by containerization, BioGAIP runs seamlessly on Windows, Linux, and macOS. Even without container support, most components can still be run natively across platforms (with minor feature limitations).
- **Broad LLM Backend Support**: Out-of-the-box support for a wide range of LLM APIs, including Grok, Qwen, Gemini, and DeepSeek, alongside full support for custom local models.
- **Secure & Flexible Architecture**: Built on a robust Client/Server (C/S) architecture utilizing `BioWorker` as the server. By leveraging containerization and sandboxing (highly experimental), it delivers exceptional scalability while keeping your sensitive data completely secure.
- **Ultimate Customizability**: Designed with power users in mind. Through a unified configuration file, you can deeply tailor the platform—fine-tuning everything from RAG pipelines and multi-agent teams to hallucination mitigation strategies.


## 📸 Demo Video of End-to-end Graphic Deploy

<video controls style="width: 100%; max-width: 100%; display: block; margin: 1rem auto;">
  <source src="./src/Supplement%20video%201.mp4" type="video/mp4">
  Your browser does not support the video tag.
</video>


### Real-World Example (Reanalysis GEO data)
    You are an expert bioinformatician tasked with processing RNA-seq sequencing data from the dataset GSE281525. The data is stored in the directory <input directory>, which includes RNA-seq data for non-metastatic tumor samples (in the subdirectory Never-met_rna_seq) and metastatic tumor samples (in the subdirectory Met_rna_seq). 
    The human reference genome hg38 and its corresponding GTF annotation file are available in <reference genome direcrory>.
    Perform the following pipeline steps on the data:
    
    1. Conduct quality control (QC) using appropriate tools such as FastQC or MultiQC.
    2. Align the reads to the hg38 reference genome using STAR.
    3. Quantify transcripts using featureCounts.
    4. Perform differential expression analysis using DESeq2 to identify genes with differential expression between non-metastatic (Never-met_rna_seq) and metastatic (Met_rna_seq) tumor samples.
    
    All outputs must be saved in <output directory>. 
    If you need to create or manage environments (e.g., Conda envs), store them in <env directory>.
    
    You have access to <cpu number> CPU cores for parallel processing where applicable.
    Expected Outputs:
    
    1. Aligned BAM files for each sample.
    2. Transcript quantification results (e.g., count matrices).
    3. A list of differentially expressed genes, including fold changes, p-values, and adjusted p-values.

→ AI downloads creates envs, runs everything, saves BAMs + DE gene table + MultiQC report.

📸 Video: 

<video controls style="width: 100%; max-width: 100%; display: block; margin: 1rem auto;">
  <source src="./src/Supplement%20video%202%20mini.mp4" type="video/mp4">
  Your browser does not support the video tag.
</video>

---

## 🚀 Quick Start (Literally few hours)

1. Install **docker** on Windows 10/11. [Get started with Docker remote containers on WSL 2](https://learn.microsoft.com/en-us/windows/wsl/tutorials/wsl-containers)
   
   If you cant install docker, BioAG also can work with limited functions
2. **Upload** Your data to your Linux server (Winscp/filezilla)
3. **Download** BioLauncher 
4. **Launch** on Windows 10/11 (WSL2 auto-detected)  
5. **Connect** to your Linux server (IP + password)  
6. **Paste** your LLM API key (Qwen / DeepSeek / local)  
7. Paste **prompt** → **Run**  

**Done.** The AI agent takes over.

**Detail Quick Start Guide** available at [here](quickstart.md)

**Configure File Template** is available [here](https://raw.githubusercontent.com/zhangjy859/BioGAIP/refs/heads/main/bioGen/document/src/configure.yaml).
(If not download automatic, please use save as, or press `Ctrl + S`)

---

## 🎯 Tested Analyses

- **Bulk RNA-seq** (DE, pathway, volcano plots)  
- **ATAC-seq / ChIP-seq** (peak calling)  
- **scRNA-seq** (Seurat/CellRanger, clustering, markers)  
- **WGS** (variant calling)
- **Custom pipelines** — just describe them!

All tools (STAR, DESeq2, CellRanger, MACS2, etc.) are auto-installed in isolated conda/docker environments.

---

## 🛡️ Security & Architecture

- **Client-Server mode**: Your raw data **never** leaves your server  
- **AGPL-3.0** open source (audit everything)  
- **Docker + sandbox** isolation  
- **High customization** for Advanced user

---

## 📊 What the Community Says

> ^_^

---

## 📚 Full Documentation

**[Guidelines](Guidelines.txt)** → Detailed guide with screenshots, prompt templates, troubleshooting, and server config examples.

---

## 🤝 Contributing & Community

We welcome:
- LLM prompt improvements  
- Bug reports  
- Feature requests

**Star ⭐ this repo** if you want the bioinformatics world to finally catch up with AI!

---

# 🌟 Milestones

We are building the future of AI-driven bioinformatics — one milestone at a time.  
Here’s our transparent roadmap:

| Milestone               | Target Date | Status     | Key Achievements & Goals  |
| ----------------------- | ----------- | ---------- | ------------------------- |
| **v1.31 — Public Beta** | March 2026  | ✅ Released | First public beta release |
| **Optimized user-defined tools support** | - | ⏳ Planned | - |
| **Optimized Logger System** | - | ⏳ Planned | - |
| **Universal MCP Support for BioWorker** | - | ⏳ Planned | - |

**Want to influence the roadmap?**  
Star ⭐ the repo and open an [issue](https://github.com/zhangjy859/BioGAIP/issues) — every suggestion is welcome!

---



## 😲Known Limitation

- Windows: If without containerization, RAG is unavailable due to tqdm output issues.

- Windows: If without containerization, Outputs from certain LLMs may fail to be correctly parsed by the frontend. This does not affect the task execution itself, but impacts the user interaction experience.

  

## 📨 Contact

If you have any question, please feel free to open an [issue](https://github.com/zhangjy859/BioGAIP/issues), or send mail to xxx#xxxx.com (Please replace # with @)

## 📝 Historical Note: BioGen vs. BioGAIP

BioGAIP was originally developed under the internal codename **BioGen** during our v1.0 cycle. While we officially rebranded to BioGAIP starting with v1.3, the internal codebase migration is still an ongoing process. 

As a result, you may still spot `BioGen` or `biogen` used in variable names, module paths, and legacy code segments. These references are completely normal and do not affect functionality.

<br>

## License
This project is licensed under a Dual License model:
1. [AGPL-3.0](https://www.gnu.org/licenses/agpl-3.0.en.html) License: You can use this software under the terms of the GNU Affero General Public License version 3.0. If you build a commercial or non-commercial application using this project, you must comply with all AGPL-3.0 terms, which includes making your entire application's source code open and available under the same license.
2. Commercial License: If you wish to use this software in a proprietary or closed-source application, or if you cannot comply with the AGPL-3.0 requirements, you must request a commercial license.

**Disclaimer**

THERE IS NO WARRANTY FOR THE PROGRAM, TO THE EXTENT PERMITTED BY APPLICABLE LAW. EXCEPT WHEN OTHERWISE STATED IN WRITING THE COPYRIGHT HOLDERS AND/OR OTHER PARTIES PROVIDE THE PROGRAM "AS IS" WITHOUT WARRANTY OF ANY KIND, EITHER EXPRESSED OR IMPLIED, INCLUDING, BUT NOT LIMITED TO, THE IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE. THE ENTIRE RISK AS TO THE QUALITY AND PERFORMANCE OF THE PROGRAM IS WITH YOU. SHOULD THE PROGRAM PROVE DEFECTIVE, YOU ASSUME THE COST OF ALL NECESSARY SERVICING, REPAIR OR CORRECTION.


