#!/bin/bash
#docker build -t ventz/whisper container
docker build --no-cache --rm=true --force-rm=true -t dford/segment-audio container
