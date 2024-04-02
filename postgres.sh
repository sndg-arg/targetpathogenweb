#!/bin/bash

docker run \
  -u $(id -u ${USER}):$(id -g ${USER}) \
  -p 5432:5432 \
  --rm \
  --name sndgr \
  -v $PWD/dbs/db:/var/lib/postgresql/data \
  -e POSTGRES_PASSWORD=123 \
  -e POSTGRES_DB=tp \
  -v /etc/passwd:/etc/passwd:ro \
  --shm-size 512m \
  postgres:14
