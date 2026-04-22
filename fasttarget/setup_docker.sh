#!/bin/bash

# Pull Docker images
docker pull sangerpathogens/roary:latest
docker pull fpocket/fpocket:4.2.2
docker pull brinkmanlab/psortb_commandline:1.0.2
docker pull mcpalumbo/corecruncher:1
docker pull mcpalumbo/bioperl:1
docker pull mcpalumbo/foldseek:1
docker pull mcpalumbo/p2rank:latest
docker pull mcpalumbo/metagraphtools:latest

echo "Docker images setup completed."