# bring in the micromamba image so we can copy files from it
FROM mambaorg/micromamba:2.3.2 as micromamba

# Builder stage to install conda environment
FROM ubuntu:22.04 as builder

USER root

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

RUN sed -i 's/archive.ubuntu.com/mirrors.tuna.tsinghua.edu.cn/g' /etc/apt/sources.list \
    && sed -i 's/security.ubuntu.com/mirrors.tuna.tsinghua.edu.cn/g' /etc/apt/sources.list && \
    apt-get update && DEBIAN_FRONTEND=noninteractive  apt-get install -y --no-install-recommends build-essential ca-certificates && \
    apt-get clean && rm -rf /var/lib/apt/lists/*

RUN /usr/local/bin/_dockerfile_initialize_user_accounts.sh && \
    /usr/local/bin/_dockerfile_setup_root_prefix.sh

USER $MAMBA_USER

SHELL ["/usr/local/bin/_dockerfile_shell.sh"]

# Optional: you can now populate a conda environment:
RUN micromamba install --yes --name base --channel conda-forge \
      jq && \
    micromamba clean --all --yes && \
    micromamba config append channels conda-forge && \
    micromamba config append channels bioconda && \
    micromamba config append channels r

RUN echo "channels:" > ~/.condarc && \
    echo "  - defaults" >> ~/.condarc && \
    echo "show_channel_urls: true" >> ~/.condarc && \
    echo "default_channels:" >> ~/.condarc && \
    echo "  - https://mirrors.tuna.tsinghua.edu.cn/anaconda/pkgs/main" >> ~/.condarc && \
    echo "  - https://mirrors.tuna.tsinghua.edu.cn/anaconda/pkgs/r" >> ~/.condarc && \
    echo "  - https://mirrors.tuna.tsinghua.edu.cn/anaconda/pkgs/msys2" >> ~/.condarc && \
    echo "custom_channels:" >> ~/.condarc && \
    echo "  conda-forge: https://mirrors.tuna.tsinghua.edu.cn/anaconda/cloud" >> ~/.condarc && \
    echo "  pytorch: https://mirrors.tuna.tsinghua.edu.cn/anaconda/cloud" >> ~/.condarc

# 设置工作目录
WORKDIR /app

RUN micromamba install -y -n base python=3.11.5 && micromamba run -n base python -m pip config set global.extra-index-url "https://mirrors.tuna.tsinghua.edu.cn/pypi/web/simple"
COPY env.yaml /tmp/env.yaml
RUN micromamba install -y -n base -f /tmp/env.yaml && \
    micromamba clean --all --yes

RUN micromamba clean --all -y && \
    rm -rf /opt/conda/pkgs /opt/conda/var /opt/conda/conda-meta && \
    find /opt/conda -name "*.pyc" -delete 2>/dev/null || true && \
    find /opt/conda -name "*.pyo" -delete 2>/dev/null || true && \
    find /opt/conda -name "*.a" -delete 2>/dev/null || true && \
    find /opt/conda -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true && \
    find /opt/conda/lib/python3.11/site-packages -name "*tests*" -type d -exec rm -rf {} + 2>/dev/null || true && \
    rm -rf /opt/conda/share/{man,doc,info} /opt/conda/include /opt/conda/lib/python3.11/idlelib

# Final stage
#FROM nvidia/cuda:12.9.0-base-ubuntu22.04
FROM ubuntu:22.04

USER root

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

RUN /usr/local/bin/_dockerfile_initialize_user_accounts.sh && \
    /usr/local/bin/_dockerfile_setup_root_prefix.sh

COPY --from=builder --chown=$MAMBA_USER:$MAMBA_USER /opt/conda /opt/conda
COPY --from=builder --chown=$MAMBA_USER:$MAMBA_USER /home/$MAMBA_USER/.condarc /home/$MAMBA_USER/.condarc

USER $MAMBA_USER

SHELL ["/usr/local/bin/_dockerfile_shell.sh"]

ENTRYPOINT ["/usr/local/bin/_entrypoint.sh"]
# Optional: if you want to customize the ENTRYPOINT and have a conda
# environment activated, then do this:
# ENTRYPOINT ["/usr/local/bin/_entrypoint.sh", "my_entrypoint_program"]

# You can modify the CMD statement as needed....
CMD ["/bin/bash"]

# 设置工作目录
WORKDIR /app

ARG MAMBA_DOCKERFILE_ACTIVATE=1  # (otherwise python will not be found)
RUN python -c 'import uuid; print(uuid.uuid4())' > /tmp/my_uuid

ENV POSTGRES_USER=postgres
ENV POSTGRES_PASSWORD=biogendata
ENV POSTGRES_DB=chainlit_db

USER root

ENV DEBIAN_FRONTEND=noninteractive
ENV TZ=Asia/Shanghai
#RUN ln -snf /usr/share/zoneinfo/$TZ /etc/localtime && echo $TZ > /etc/timezone && \
#    cp /etc/apt/sources.list /etc/apt/sources.list.bak && \
#    sed -i 's|http://archive.ubuntu.com/ubuntu/|https://mirrors.tuna.tsinghua.edu.cn/ubuntu/|g' /etc/apt/sources.list && \
#    sed -i 's|http://security.ubuntu.com/ubuntu/|https://mirrors.tuna.tsinghua.edu.cn/ubuntu/|g' /etc/apt/sources.list && \
#    apt-get update && apt-get install -y postgresql postgresql-contrib
RUN ln -snf /usr/share/zoneinfo/$TZ /etc/localtime && echo $TZ > /etc/timezone && \
    cp /etc/apt/sources.list /etc/apt/sources.list.bak && \
    apt-get update && apt-get install -y postgresql postgresql-contrib
RUN mkdir -p /var/lib/postgresql/data

#COPY db_init.sh /docker-entrypoint-initdb.d/db_init.sh
COPY init.sql /docker-entrypoint-initdb.d/init.sql
RUN apt-get update && apt-get install -y \
    fonts-liberation \
    libasound2 \
    libatk-bridge2.0-0 \
    libatk1.0-0 \
    libatspi2.0-0 \
    libcups2 \
    libdbus-1-3 \
    libdrm2 \
    libgbm1 \
    libgtk-3-0 \
#    libgtk-4-1 \
    libnspr4 \
    libnss3 \
    libwayland-client0 \
    libxcomposite1 \
    libxdamage1 \
    libxfixes3 \
    libxkbcommon0 \
    libxrandr2 \
    xdg-utils \
    libu2f-udev \
    libvulkan1
 # Chrome instalation 

USER $MAMBA_USER

ENV VERSION_OLD=1.3.0.10
ENV VERSION=1.3.0.16


RUN micromamba run -n base pip install paramiko #&& 
    #micromamba run -n base playwright install

USER root

RUN chsh -s /usr/sbin/nologin root

#CMD ["bash", "/docker-entrypoint-initdb.d/db_init.sh"]

COPY --chown=$MAMBA_USER:$MAMBA_USER bioGen /app/bioGen
COPY --chown=$MAMBA_USER:$MAMBA_USER .chainlit /app/.chainlit
#COPY --chown=$MAMBA_USER:$MAMBA_USER .streamlit /app/.streamlit

#RUN service postgresql start && \
#    until pg_isready -h localhost -U postgres; do sleep 1; done && \
#    su - postgres -c "psql -c \"ALTER USER postgres PASSWORD '$POSTGRES_PASSWORD';\"" && \
#    su - postgres -c "createdb -O $POSTGRES_USER $POSTGRES_DB" && \
#    micromamba run -n base python /app/bioGen/web/psql_demo.py

RUN echo "" > /app/__init__.py

# chown -R postgres:postgres /var/lib/postgresql && \
RUN apt-get update && apt-get install -y gosu && \
    apt-get install -y sshpass wget && \
    chmod -R 0750 /var/lib/postgresql

USER root

COPY --chown=$MAMBA_USER:$MAMBA_USER start.sh /app/start.sh
COPY --chown=$MAMBA_USER:$MAMBA_USER start_script.sh /app/start_script.sh
COPY --chown=$MAMBA_USER:$MAMBA_USER ./bioGen/config/agent_config.yaml /config/agent_config.yaml
RUN ln -s /home/$MAMBA_USER/.cache /cache
RUN cd /cache && \
         mkdir -p chroma/onnx_models/all-MiniLM-L6-v2 
#        cd chroma/onnx_models/all-MiniLM-L6-v2 && \
#        wget https://chroma-onnx-models.s3.amazonaws.com/all-MiniLM-L6-v2/onnx.tar.gz && \
#        tar zxvf onnx.tar.gz && \
#        cd -
#RUN cd /cache && \
#        mkdir -p chroma/onnx_models/all-MiniLM-L6-v2 && \
#	cd -
COPY --chown=$MAMBA_USER:$MAMBA_USER onnx.tar.gz /cache/chroma/onnx_models/all-MiniLM-L6-v2/onnx.tar.gz
RUN cd /cache/chroma/onnx_models/all-MiniLM-L6-v2 && \
	tar zxvf onnx.tar.gz && \
        rm onnx.tar.gz && \
	cd -

#USER $MAMBA_USER

#RUN cd /app/ && micromamba run -n base python -m pip install -e .

ENV PYTHONPATH=$PYTHONPATH:/app/

ENTRYPOINT ["/usr/local/bin/_entrypoint.sh", "/app/start_script.sh"]
