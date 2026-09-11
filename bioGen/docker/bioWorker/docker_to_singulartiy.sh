docker build -t bioworker:latest .
singularity build bioworker.sif docker-daemon://bioworker:latest
