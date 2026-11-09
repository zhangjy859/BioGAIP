mkdir -p ./bioGen
rsync -avu -c --exclude='docker/' --exclude='nf_pipeline_meta/nf_cores_repos/' --exclude='nf_pipeline_meta/snakemake-workflows-repos/' --exclude='*conda_packages.json' --exclude='*.json' --exclude='*.pkl' --exclude='*.html' --exclude='*.log' --exclude 'windows_gui' --exclude 'system_config.yaml' --exclude 'system_config.yaml*' --exclude 'script/env/' --exclude 'cf_web/*' --exclude "document/*" --exclude "debug/*" \
 --exclude "config/*" --exclude 'datamodel/*' --exclude "config_gemini/" --exclude "*/.git/" --exclude "*.tar.*" --exclude "cpython-3.12.11+20250828-x86_64-pc-windows-msvc-install_only_stripped" --exclude "*.venv/*" \
 --exclude "*node_modules/*" --exclude "*out/*" --exclude "script/windows_gui_v2/python/*" --exclude "*venv*" --exclude "*.tar.gz" \
 ../../ ./bioGen
rsync -avu ../../../.chainlit ./.chainlit
rsync -avu ../../../.streamlit ./.streamlit
mkdir -p ./bioGen/docker && \
  rsync -avu ../bioWorker/* ./bioGen/docker/bioWorker/
