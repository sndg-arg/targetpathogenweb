FROM node:19.4.0
WORKDIR /usr/app
RUN npm install -g --save-dev webpack webpack-cli
# https://stackoverflow.com/questions/69692842/error-message-error0308010cdigital-envelope-routinesunsupported
ENV NODE_OPTIONS --openssl-legacy-provider
