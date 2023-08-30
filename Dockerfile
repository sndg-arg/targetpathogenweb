FROM ubuntu:latest
LABEL authors="eze"

ENTRYPOINT ["top", "-b"]