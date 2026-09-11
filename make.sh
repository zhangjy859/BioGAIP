#!/bin/bash
set -euo pipefail
echo copy files
mkdir -p biolancher/script/windows_gui/bioag
rsync -avu --exclude='*docker*' --exclude='*node*' --exclude='*.mp4' --exclude='*.md' bioGen biolancher/script/windows_gui/bioag/
rsync -avu biolancher/script/windows_gui/bioag/bioGen bioGen/docker/bio_ag
echo copy files for a known issue workaround.
# bug fix
mkdir -p biolancher/script/windows_gui/bioag/bioGen/web/bioag/bioGen
rsync -avu bioGen/ulits biolancher/script/windows_gui/bioag/bioGen/web/bioag/bioGen/

cd bioGen/pip_package

bash ./fetch_file.sh 

cd -

echo "Build docker images"
cd bioGen/docker/bio_ag && \
    mkdir -p .chainlit && \
    trap 'rm -rf -- "bioGen/docker/bio_ag/.chainlit"' EXIT && \
    docker build -t bioag:latest . && \
    cd -

## save to tar.gz
docker save bioag:latest | gzip > bioag_latest.tar.gz

cd bioGen/docker/bioWorker && \
    mkdir -p .chainlit && \
    trap 'rm -rf -- "bioGen/docker/bioWorker/.chainlit"' EXIT && \
    docker build -t bioworker:latest . && \
    cd -

## bash ./docker_to_singulartiy.sh

## save to tar.gz
docker save bioworker:latest | gzip > bioworker_latest.tar.gz

echo "#bioGen git rule"
echo "biolancher/script/windows_gui/out" > .gitignore
echo "biolancher/script/windows_gui/python" >> .gitignore
echo "nf_pipeline_meta/*" >> .gitignore
echo "conda_pkg_meta/*" >> .gitignore
echo "bioGen/document/_book/*" >> .gitignore
echo "biolancher/script/windows_gui/node_modules/*" >> .gitignore
echo "biolancher/script/windows_gui/python/*" >> .gitignore
echo "biolancher/script/windows_gui/info/*" >> .gitignore
echo "/bioag_latest.tar.gz" >> .gitignore
echo "/bioworker_latest.tar.gz" >> .gitignore
echo "bioGen/docker/bioWorker/bioworker.sif" >> .gitignore
echo "bioGen/docker/bio_ag/onnx.tar.gz" >> .gitignore
echo "bioGen/document/node_modules/*" >> .gitignore
echo "bak/*" >> .gitignore
echo "biolancher/script/windows_gui_v2/bioag/onnx.tar.gz" >> .gitignore
echo "biolancher/script/windows_gui_v2/python/*" >> .gitignore

sed -i -E 's#\./(src|img)#./bioGen/document/\1#g' README.md

#git rev-parse --is-inside-worktree &> /dev/null || \
#    (echo "Initializing Git repository..." && git init && git add . && echo "Done ✔")
#
#"Message: $@"

echo 'done'
