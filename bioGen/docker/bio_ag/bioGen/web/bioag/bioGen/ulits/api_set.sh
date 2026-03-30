#!/bin/bash
# set -euo pipefail
## get script path

## args is server_ip, username, port, ssh_password, api_key
SERVER_IP="$1"
USERNAME="$2"
PORT="$3"
SSH_PASSWORD="$4"
API_KEY="$5"
RO_DIR="$6"
RW_DIR="$7"
WORK_DIR="$8"
if [ $# -eq 8 ]; then
    ALLOW_RAW=""
else
    ALLOW_RAW="$9"
fi
if [ -n "$ALLOW_RAW" ]; then
    ALLOW_RAW=1
else
    ALLOW_RAW=0
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
web_api_file="$SCRIPT_DIR/web_shell_command_v2.py"
web_api_docker="$SCRIPT_DIR/../docker/bioWorker"

## SSH command to execute the Python script on the remote server
## check docker install in remote server
docker=1
sshpass -p "$SSH_PASSWORD" ssh -o StrictHostKeyChecking=no -p "$PORT" "$USERNAME@$SERVER_IP" "docker --version"
if [ $? -ne 0 ]; then
    echo "Docker is not installed on the remote server. Please install Docker and try again."
    docker=0
fi
sshpass -p "$SSH_PASSWORD" ssh -o StrictHostKeyChecking=no -p "$PORT" "$USERNAME@$SERVER_IP" "docker run hello-world > /dev/null 2>&1"
if [ $? -ne 0 ]; then
    echo "Docker is not running properly on the remote server. Please check Docker installation and try again."
    docker=0
fi
singularity=1
sshpass -p "$SSH_PASSWORD" ssh -o StrictHostKeyChecking=no -p "$PORT" "$USERNAME@$SERVER_IP" "singularity --version > /dev/null 2>&1"
if [ $? -ne 0 ] && [ $docker -ne 0 ]; then
    echo "Singularity is not installed on the remote server. Please install Singularity and try again."
    singularity=0
fi

## if port 38000 is occupied, exit
check_port() {
    # use lsof to check if port is occupied
    sshpass -p "$SSH_PASSWORD" ssh -o StrictHostKeyChecking=no -p "$PORT" "$USERNAME@$SERVER_IP" "lsof -i :38000 > /dev/null 2>&1"
    return $?
}

## if non docker, create dir for api
if [ $docker -eq 0 ] && [ $singularity -eq 0 ] && [ $ALLOW_RAW -eq 1 ]; then
    sshpass -p "$SSH_PASSWORD" ssh -o StrictHostKeyChecking=no -p "$PORT" "$USERNAME@$SERVER_IP" "mkdir -p ~/bioGen"
    ## scp file to remote server
    sshpass -p "$SSH_PASSWORD" scp -P "$PORT" "$web_api_file" "$USERNAME@$SERVER_IP:~/bioGen/"
    ## run python script on remote server
    ## set API key as env variable
    export WORK_DIR=${WORK_DIR:-~/.cache/.bioWorker}
    sshpass -p "$SSH_PASSWORD" ssh -o StrictHostKeyChecking=no -p "$PORT" "$USERNAME@$SERVER_IP" "export API_KEY='$API_KEY' && python3 ~/bioGen/web_shell_command_v2.py" &
    echo "Sucessfully started bioGen API server with python script on $SERVER_IP:38000"
    exit 0
fi

## if docker, run docker command
if [ $docker -eq 1 ]; then
    sshpass -p "$SSH_PASSWORD" ssh -o StrictHostKeyChecking=no -p "$PORT" "$USERNAME@$SERVER_IP" "mkdir -p ~/bioGen"
    # scp web_api_docker directory to remote server
    sshpass -p "$SSH_PASSWORD" scp -r -P "$PORT" "$web_api_docker" "$USERNAME@$SERVER_IP:~/bioGen/"
    ## cd and run docker compose
    ## split RO_DIR and RW_DIR by ; to list
    IFS=';' read -r -a ro_array <<< "$RO_DIR"
    IFS=';' read -r -a rw_array <<< "$RW_DIR"
    ## create volume string
    volume_str=""
    for ro in "${ro_array[@]}"; do
        volume_str+="-v $ro:$ro:ro "
    done
    for rw in "${rw_array[@]}"; do
        volume_str+="-v $rw:$rw "
    done
    if [ -n "$WORK_DIR" ]; then
        volume_str+="-v $WORK_DIR:/data/work_dir "
    fi
    ## run docker compose with volume string
    ## first bulid image
    echo "Clean existing environment"
    sshpass -p "$SSH_PASSWORD" ssh -o StrictHostKeyChecking=no -p "$PORT" "$USERNAME@$SERVER_IP" "cd ~/bioGen/bioWorker && docker stop bioworker > /dev/null 2>&1 & sleep 3 & docker rm bioworker > /dev/null 2>&1 || echo "No existing bioworker container to stop.""
    echo "Building Docker image on remote server..."
    sshpass -p "$SSH_PASSWORD" ssh -o StrictHostKeyChecking=no -p "$PORT" "$USERNAME@$SERVER_IP" "cd ~/bioGen/bioWorker && docker build -t bioworker:lastest ."

    ## check port 38000
    check_port
    if [ $? -eq 0 ]; then
        echo "Port 38000 is already in use on the remote server. Please free the port and try again."
        exit 1
    fi

    ## then run docker compose with env variable
    echo "Starting Docker container on remote server..."
    sshpass -p "$SSH_PASSWORD" ssh -o StrictHostKeyChecking=no -p "$PORT" "$USERNAME@$SERVER_IP" "cd ~/bioGen/bioWorker && API_KEY='$API_KEY' docker run -detach --name bioworker -e API_KEY='$API_KEY' -p 38000:38000 $volume_str bioworker:lastest"

    sleep 10

    echo Sucessfully started bioGen API server in docker on $SERVER_IP:38000
    exit 0
fi

if [ $docker -eq 0 ] && [ $singularity -eq 1 ]; then
    sshpass -p "$SSH_PASSWORD" ssh -o StrictHostKeyChecking=no -p "$PORT" "$USERNAME@$SERVER_IP" "mkdir -p ~/bioGen"
    ## scp file to remote server
    sshpass -p "$SSH_PASSWORD" scp -P "$PORT" "$web_api_file" "$USERNAME@$SERVER_IP:~/bioGen/"
    singularity_sif="$SCRIPT_DIR/biogen_worker.sif"
    ## scp singularity sif to remote server
    sshpass -p "$SSH_PASSWORD" scp -P "$PORT" "$singularity_sif" "$USERNAME@$SERVER_IP:~/bioGen/"
    ## check port 38000
    check_port

    if [ $? -eq 0 ]; then
        echo "Port 38000 is already in use on the remote server. Please free the port and try again."
        exit 1
    fi

    ## run singularity command on remote server
    ## split RO_DIR and RW_DIR by ; to list
    IFS=';' read -r -a ro_array <<< "$RO_DIR"
    IFS=';' read -r -a rw_array <<< "$RW_DIR"
    ## create volume string
    volume_str=""
    for ro in "${ro_array[@]}"; do
        volume_str+="-B $ro:$ro:ro "
    done
    for rw in "${rw_array[@]}"; do
        volume_str+="-B $rw:$rw "
    done
    if [ -n "$WORK_DIR" ]; then
        volume_str+="-B $WORK_DIR:/data/work_dir "
    fi
    ## run singularity command with volume string
    sshpass -p "$SSH_PASSWORD" ssh -o StrictHostKeyChecking=no -p "$PORT" "$USERNAME@$SERVER_IP" "export API_KEY='$API_KEY' && singularity exec $volume_str ~/bioGen/biogen_worker.sif python3 ~/bioGen/web_shell_command_v2.py" &
    echo "Sucessfully started bioGen API server with singularity on $SERVER_IP:38000"
    exit 0
fi

exit 9
