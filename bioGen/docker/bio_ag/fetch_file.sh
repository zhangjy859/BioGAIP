mkdir -p ./bioGen
rsync -avu -c --exclude='docker/' --exclude='nf_pipeline_meta/nf_cores_repos/' --exclude='nf_pipeline_meta/snakemake-workflows-repos/' --exclude='*conda_packages.json' --exclude='*.json' --exclude='*.pkl' --exclude='*.html' --exclude='*.log' --exclude 'windows_gui' --exclude 'system_config.yaml' --exclude 'system_config.yaml*' --exclude 'script/env/' ../../ ./bioGen
rsync -avu ../../../.chainlit ./.chainlit
rsync -avu ../../../.streamlit ./.streamlit
mkdir -p ./bioGen/docker && \
  rsync -avu ../bioWorker/* ./bioGen/docker/bioWorker/
