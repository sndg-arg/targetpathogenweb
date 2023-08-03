FROM node:19.4.0
RUN apt update && apt -y install samtools tabix genometools

WORKDIR /
RUN npm install -g --save-dev @jbrowse/cli serve@14.2.0
RUN jbrowse create jbrowse2

# https://stackoverflow.com/questions/69692842/error-message-error0308010cdigital-envelope-routinesunsupported
ENV NODE_OPTIONS --openssl-legacy-provider
WORKDIR /jbrowse2
