#!/bin/bash

# Navigate to the js directory
cd js || exit

docker --version
# Build the Docker image named webpack
docker build -t webpack .

# Run a container from the webpack image, install npm packages, then exit
docker run --rm -w $PWD -v $PWD:$PWD webpack bash -c 'npm install'

# Return to the parent directory
cd .. || exit

# Wait for PostgreSQL to become available
echo "Waiting for PostgreSQL..."
while ! PGPASSWORD=$POSTGRES_PASSWORD psql -U $POSTGRES_USER -h db -c '\q'; do
  sleep 1
done
echo "PostgreSQL is ready."

# Apply migrations
python manage.py migrate

# Start Django development server
exec python manage.py runserver 0.0.0.0:8000
