#!/bin/bash

# Check if /app/.env exists and source it if it does
if [ -f /app/.env ]; then
    source /app/.env
    # Export the variables to make them available to subprocesses
    while IFS= read -r line; do
        # Skip comments and empty lines
        if [[ ! "$line" =~ ^[[:space:]]*(#|$) ]] && [[ "$line" =~ = ]]; then
            key="${line%%=*}"
            export "$key"
        fi
    done < /app/.env
fi

# Get the first parameter (can be empty)
param="$1"

if [ "$param" = "chainlit" ]; then
    # Execute script a (replace with actual command or script path, e.g., chainlit run app.py)
    echo "Executing script a for chainlit"
    # Example: chainlit run /app/chainlit_app.py
    chainlit run bioGen/web/app_chainlit1.py --port 8501
    # Add actual execution here

elif [ "$param" = "streamlit" ]; then
    # Execute script b (replace with actual command or script path, e.g., streamlit run app.py)
    echo "Executing script b for streamlit"
    # Example: streamlit run /app/streamlit_app.py
    streamlit run bioGen/web/app_streamlit1.py --server.port 8501
    # Add actual execution here

elif [ -z "$param" ]; then
    # Check if running in interactive environment (stdin is a terminal)
    if [ -t 0 ]; then
        # Execute script c (replace with actual command or script path, e.g., /bin/bash)
        echo "Executing script bipgen.py in interactive mode"
        # Example: /app/script_c.sh or exec /bin/bash
        python bioGen/biogen.py
        # Add actual execution here
    else
        # Exit if not interactive and no parameter
        exit 0
    fi

else
    # Optional: Handle invalid parameter
    echo "Invalid parameter: $param"
    exit 1
fi