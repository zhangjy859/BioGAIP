# bring in the micromamba image so we can copy files from it
FROM mambaorg/micromamba:2.3.2 as micromamba

# Builder stage to install conda environment
FROM ubuntu:22.04 as builder

USER root

# if your image defaults to a non-root user, then you may want to make the
# next 3 ARG commands match the values in your image. You can get the values
# by running: docker run --rm -it my/image id -a
ARG MAMBA_USER=mambauser
ARG MAMBA_USER_ID=57439
ARG MAMBA_USER_GID=57439
ENV MAMBA_USER=$MAMBA_USER
ENV MAMBA_ROOT_PREFIX="/opt/conda"
ENV MAMBA_EXE="/bin/micromamba"

COPY --from=micromamba "$MAMBA_EXE" "$MAMBA_EXE"
COPY --from=micromamba /usr/local/bin/_activate_current_env.sh /usr/local/bin/_activate_current_env.sh
COPY --from=micromamba /usr/local/bin/_dockerfile_shell.sh /usr/local/bin/_dockerfile_shell.sh
COPY --from=micromamba /usr/local/bin/_entrypoint.sh /usr/local/bin/_entrypoint.sh
COPY --from=micromamba /usr/local/bin/_dockerfile_initialize_user_accounts.sh /usr/local/bin/_dockerfile_initialize_user_accounts.sh
COPY --from=micromamba /usr/local/bin/_dockerfile_setup_root_prefix.sh /usr/local/bin/_dockerfile_setup_root_prefix.sh

ENV DEBIAN_FRONTEND noninteractive
ENV TZ=Asia/Kolkata DEBIAN_FRONTEND=noninteractive
RUN apt-get update && apt install tzdata -y && apt install net-tools vim man file -y
RUN apt-get install -y build-essential
RUN yes| unminimize
RUN apt-get update -y && apt-get upgrade -y && apt-get install ubuntu-minimal ubuntu-server-minimal -y
RUN apt-get install -y vim perl wget tar man sudo adduser netstat-nat net-tools curl git w3m
RUN /usr/local/bin/_dockerfile_initialize_user_accounts.sh && \
    /usr/local/bin/_dockerfile_setup_root_prefix.sh

USER $MAMBA_USER

SHELL ["/usr/local/bin/_dockerfile_shell.sh"]


# Optional: you can now populate a conda environment:
RUN micromamba install --yes --name base --channel conda-forge \
      jq git git-lfs git-delta lazygit gitui && \
    micromamba clean --all --yes

# set app work directory
WORKDIR /app

# cop necessary environment resource
COPY --chown=$MAMBA_USER:$MAMBA_USER env.yaml /tmp/env.yaml

RUN micromamba install -y -n base -f /tmp/env.yaml && \
    micromamba clean --all --yes

RUN micromamba config set show_channel_urls true && \
    micromamba config prepend default_channels https://mirrors.tuna.tsinghua.edu.cn/anaconda/pkgs/main && \
    micromamba config prepend default_channels https://mirrors.tuna.tsinghua.edu.cn/anaconda/pkgs/r && \
    micromamba config prepend default_channels https://mirrors.tuna.tsinghua.edu.cn/anaconda/pkgs/msys2 && \
    micromamba config set custom_channels.conda-forge https://mirrors.tuna.tsinghua.edu.cn/anaconda/cloud && \
    micromamba config set custom_channels.pytorch https://mirrors.tuna.tsinghua.edu.cn/anaconda/cloud && \
    micromamba config set channel_priority strict && \
    micromamba config append channels bioconda

RUN micromamba install -y -n base -c conda-forge -c bioconda \
    biopython pysam htseq pybedtools \
    fastqc multiqc trimmomatic cutadapt fastp \
    bowtie2 bwa hisat2 star minimap2 \
    samtools bcftools bedtools picard \
    -y
RUN micromamba install -y -n base -c conda-forge -c bioconda spades megahit unicycler \
    gatk4 freebayes varscan \
    snakemake nextflow \
    r-base r-ggplot2 r-dplyr \
    blast hmmer prodigal \
    -y
RUN micromamba install -y -n base -c conda-forge -c bioconda qualimap bamtools deeptools \
    seqtk sickle trim-galore \
    -y

RUN micromamba clean --all --yes

# Final stage
FROM ubuntu:22.04

USER root

# if your image defaults to a non-root user, then you may want to make the
# next 3 ARG commands match the values in your image. You can get the values
# by running: docker run --rm -it my/image id -a
ARG MAMBA_USER=mambauser
ARG MAMBA_USER_ID=57439
ARG MAMBA_USER_GID=57439
ENV MAMBA_USER=$MAMBA_USER
ENV VERSION=1.3.0
ENV MAMBA_ROOT_PREFIX="/opt/conda"
ENV MAMBA_EXE="/bin/micromamba"

COPY --from=micromamba "$MAMBA_EXE" "$MAMBA_EXE"
COPY --from=micromamba /usr/local/bin/_activate_current_env.sh /usr/local/bin/_activate_current_env.sh
COPY --from=micromamba /usr/local/bin/_dockerfile_shell.sh /usr/local/bin/_dockerfile_shell.sh
COPY --from=micromamba /usr/local/bin/_entrypoint.sh /usr/local/bin/_entrypoint.sh
COPY --from=micromamba /usr/local/bin/_dockerfile_initialize_user_accounts.sh /usr/local/bin/_dockerfile_initialize_user_accounts.sh
COPY --from=micromamba /usr/local/bin/_dockerfile_setup_root_prefix.sh /usr/local/bin/_dockerfile_setup_root_prefix.sh

RUN /usr/local/bin/_dockerfile_initialize_user_accounts.sh && \
    /usr/local/bin/_dockerfile_setup_root_prefix.sh && \
    micromamba config append channels bioconda && \
    micromamba config append channels conda-forge && \
    micromamba config set channel_priority strict

RUN micromamba clean --locks

RUN apt update && apt install -y curl iputils-ping wget parallel tree build-essential

RUN rm -rf /var/lib/apt/lists

COPY --from=builder --chown=$MAMBA_USER:$MAMBA_USER /opt/conda /opt/conda
RUN chmod a+rwx -R /opt/conda/conda-meta/

## safely enhance
RUN chsh -s /usr/sbin/nologin root

USER $MAMBA_USER

SHELL ["/usr/local/bin/_dockerfile_shell.sh"]

ENTRYPOINT ["/usr/local/bin/_entrypoint.sh"]
# Optional: if you want to customize the ENTRYPOINT and have a conda
# environment activated, then do this:
# ENTRYPOINT ["/usr/local/bin/_entrypoint.sh", "my_entrypoint_program"]

# You can modify the CMD statement as needed....
CMD ["/bin/bash"]

# set app work directory
WORKDIR /app

COPY --chown=$MAMBA_USER:$MAMBA_USER web_shell_command_v5.py /app/web_shell_command_v5.py
RUN chmod -R a+rwx /app

CMD ["python", "web_shell_command_v2.py"]

ARG MAMBA_DOCKERFILE_ACTIVATE=1  # (otherwise python will not be found)
RUN echo "use_lockfiles: false" >> ~/.mambarc
RUN python -c 'import uuid; print(uuid.uuid4())' > /tmp/my_uuidi

ENTRYPOINT ["/usr/local/bin/_entrypoint.sh", "python", "web_shell_command_v5.py"]
