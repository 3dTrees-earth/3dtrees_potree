#!/bin/bash

docker run -it --rm \
    --cpus=10 \
    --memory=50g \
    -u $(id -u kg281):$(id -g kg281) \
    -v /home/kg281/data/debug/417/single_small:/data \
    3dtrees_potree_patch \
    python /src/run.py \
    --source /data/ \
    --outdir output_potree