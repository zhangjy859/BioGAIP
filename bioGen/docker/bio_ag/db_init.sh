#!/bin/bash

service postgresql start

sleep 5

su - postgres -c "psql -c \"CREATE USER ${POSTGRES_USER} WITH PASSWORD '${POSTGRES_PASSWORD}';\""
su - postgres -c "psql -c \"CREATE DATABASE ${POSTGRES_DB} OWNER ${POSTGRES_USER};\""

su - postgres -c "psql -U ${POSTGRES_USER} -d ${POSTGRES_DB} -f /docker-entrypoint-initdb.d/init.sql"

tail -f /dev/null
