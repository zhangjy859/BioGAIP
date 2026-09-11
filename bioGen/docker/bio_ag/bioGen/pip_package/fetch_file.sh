mkdir -p ./src/bioGen
rsync -av --files-from=file_list.txt ../ ./src/bioGen/

echo "" > ./src/bioGen/pubmed/__init__.py
echo "" > ./src/bioGen/config/__init__.py
echo "" > ./src/bioGen/web_v2/__init__.py

cp cli.py ./src/bioGen/cli.py
#rsync -avu ../../../.chainlit ./.chainlit
#rsync -avu ../../../.streamlit ./.streamlit
