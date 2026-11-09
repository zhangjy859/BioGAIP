#!/bin/bash

# Script: run_container.sh
# Description: Launches a container using Docker or Singularity with specified mounts and frontend.
# Usage: ./run_container.sh [front_ui] [configure_file] [conda_meta_db] [workflow_db] [user_ext_db] [cache_dir] [http_proxy]
#        ./run_container.sh stop
# Defaults: front_ui=CLI, others optional.

set -euo pipefail

# Container configuration
CONTAINER_IMAGE="bioag:latest"
CONTAINER_NAME="bioag"
MOUNT_BASE="/data"

# Function to check if Docker is available
check_docker() {
    if command -v docker >/dev/null 2>&1; then
        echo "docker"
        return 0
    fi
    return 1
}

# Function to check if Singularity is available
check_singularity() {
    if command -v singularity >/dev/null 2>&1; then
        echo "singularity"
        return 0
    fi
    return 1
}

# Function to determine container engine
get_engine() {
    if check_docker; then
        echo "docker"
    elif check_singularity; then
        echo "singularity"
    else
        echo "error: Neither Docker nor Singularity is installed." >&2
        exit 1
    fi
}

# Function to start container with Docker
start_docker() {
    local front_ui="$1"
    local configure="$2"
    local conda_meta="$3"
    local workflow="$4"
    local user_ext="$5"
    local cache="$6"
    local proxy="$7"

    # Build mount flags
    local mounts=()
    if [[ -n "$configure" ]]; then
        mounts+=("-v" "$configure:/config/system_config.yaml:ro")
    fi
    if [[ -n "$conda_meta" ]]; then
        mounts+=("-v" "$conda_meta:$MOUNT_BASE/conda_meta:rw")
    fi
    if [[ -n "$workflow" ]]; then
        mounts+=("-v" "$workflow:$MOUNT_BASE/pipelines_meta:rw")
    fi
    if [[ -n "$user_ext" ]]; then
        mounts+=("-v" "$user_ext:$MOUNT_BASE/user_ext:rw")
    fi
    if [[ -n "$cache" ]]; then
        mounts+=("-v" "$cache:/cache")
    fi

    # Environment
    local envs=()
    if [[ -n "$proxy" ]]; then
        envs+=("--env" "http_proxy=$proxy" "--env" "https_proxy=$proxy")
    fi

    # Command
    local cmd_args=()
    if [[ "$front_ui" != "CLI" ]]; then
        cmd_args=("$front_ui")
    fi

    # Run container
    docker run -rm \
        --name "$CONTAINER_NAME" \
        "${mounts[@]}" \
        "${envs[@]}" \
        -it \
        "$CONTAINER_IMAGE" \
        "${cmd_args[@]}"
}

# Function to start container with Singularity
start_singularity() {
    echo "Singularity support is basic; adjust as needed for full mounts." >&2
    local front_ui="$1"
    local configure="$2"
    local conda_meta="$3"
    local workflow="$4"
    local user_ext="$5"
    local cache="$6"
    local proxy="$7"

    # Singularity bind mounts (format: --bind host_path:container_path)
    local binds=()
    if [[ -n "$configure" ]]; then
        binds+=("--bind" "$configure:/configure:ro")
    fi
    if [[ -n "$conda_meta" ]]; then
        binds+=("--bind" "$conda_meta:$MOUNT_BASE/conda_meta:ro")
    fi
    if [[ -n "$workflow" ]]; then
        binds+=("--bind" "$workflow:$MOUNT_BASE/pipelines_meta:ro")
    fi
    if [[ -n "$user_ext" ]]; then
        binds+=("--bind" "$user_ext:$MOUNT_BASE/user_ext:ro")
    fi
    if [[ -n "$cache" ]]; then
        binds+=("--bind" "$cache:/cache")
    fi

    # Environment
    local env_cmd=()
    if [[ -n "$proxy" ]]; then
        env_cmd+=("export http_proxy=$proxy")
    fi

    # Command
    local cmd=()
    if [[ "$front_ui" != "CLI" ]]; then
        cmd+=("$front_ui")
    fi
    cmd+=("${env_cmd[@]}")

    # Run in background (Singularity doesn't have direct detach like Docker; use nohup or screen)
    nohup singularity run \
        "${binds[@]}" \
        --contain \
        --cleanenv \
        -B /tmp \
        "$CONTAINER_IMAGE" \
        "${cmd[@]}" > /dev/null 2>&1 &
}

# Function to stop container
stop_container() {
    local engine="$1"
    case "$engine" in
        docker)
            if docker ps --filter "name=$CONTAINER_NAME" --format "table {{.Names}}" | grep -q "$CONTAINER_NAME"; then
                docker stop "$CONTAINER_NAME" && docker rm "$CONTAINER_NAME"
                echo "Stopped and removed Docker container $CONTAINER_NAME"
            else
                echo "No running Docker container named $CONTAINER_NAME"
            fi
            ;;
        singularity)
            # Singularity instances; adjust if using instance start
            singularity instance stop "$CONTAINER_NAME" 2>/dev/null || echo "No running Singularity instance $CONTAINER_NAME"
            ;;
    esac
}

# Main parameter parsing
FRONT_UI="CLI"
CONFIGURE=""
CONDA_META=""
WORKFLOW=""
USER_EXT=""
CACHE=""
PROXY=""

if [[ $# -eq 0 ]]; then
    echo "Usage: $0 [front_ui] [configure_file] [conda_meta_db] [workflow_db] [user_ext_db] [cache_dir] [http_proxy]"
    echo "       $0 stop"
    exit 1
fi

if [[ "${1:-}" == "stop" ]]; then
    ENGINE=$(get_engine)
    stop_container "$ENGINE"
    exit 0
fi

# Shift for positional args
FRONT_UI="${1:-CLI}"
shift

while [[ $# -gt 0 ]]; do
    case "$1" in
        streamlit|chainlit|CLI)
            FRONT_UI="$1"
            ;;
        *)
            if [[ -z "$CONFIGURE" ]]; then
                CONFIGURE="$1"
            elif [[ -z "$CONDA_META" ]]; then
                CONDA_META="$1"
            elif [[ -z "$WORKFLOW" ]]; then
                WORKFLOW="$1"
            elif [[ -z "$USER_EXT" ]]; then
                USER_EXT="$1"
            elif [[ -z "$CACHE" ]]; then
                CACHE="$1"
            elif [[ -z "$PROXY" ]]; then
                PROXY="$1"
            fi
            ;;
    esac
    shift
done

# Validate front_ui
if [[ "$FRONT_UI" != "streamlit" && "$FRONT_UI" != "chainlit" && "$FRONT_UI" != "CLI" ]]; then
    echo "Error: front_ui must be 'streamlit', 'chainlit', or 'CLI'" >&2
    exit 1
fi

# Get engine and start
ENGINE=$(get_engine)
case "$ENGINE" in
    docker)
        start_docker "$FRONT_UI" "$CONFIGURE" "$CONDA_META" "$WORKFLOW" "$USER_EXT" "$CACHE" "$PROXY"
        echo "Started Docker container $CONTAINER_NAME with front_ui=$FRONT_UI"
        ;;
    singularity)
        start_singularity "$FRONT_UI" "$CONFIGURE" "$CONDA_META" "$WORKFLOW" "$USER_EXT" "$CACHE" "$PROXY"
        echo "Started Singularity instance $CONTAINER_NAME with front_ui=$FRONT_UI"
        ;;
esac