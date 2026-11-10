#!/bin/bash
set -euo pipefail

#exec gosu root "service postgresql start"
## get env env variable
if [ $# -eq 1 ]; then
   echo "$@"
   front_ui=$1
else
   front_ui=${FRONT_UI:-streamlit}
fi
echo "Front UI is $front_ui"
sleep 5
if [ "$front_ui" == "streamlit" ]; then
    echo "Starting Streamlit UI..."
    ## start streamlit ui
    cd /app
    streamlit run bioGen/web/app_streamlit1.py --server.port 8501
elif [ "$front_ui" == "chainlit" ]; then
    echo "Starting Chainlit UI..."
    ## start chainlit ui
    cd /app
    chainlit run bioGen/web/app_chainlit1.py --port 8501
elif [ "$front_ui" == "cli" ]; then
    echo "Starting CLI UI..."
    cd /app
    python bioGen/biogen.py
else
    echo "Invalid FRONT_UI value. Please set it to 'streamlit' or 'chain', will run as CMD mode."
    cd /app
    python bioGen/biogen.py
fi

tail -f /dev/null
