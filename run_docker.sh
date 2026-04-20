#!/bin/bash

INPUT_FOLDER=/home/kg281/data/debug/818/products/standard
NUMTHREADS=10

docker run -it --rm \
    --cpus=10 \
    --memory=100g \
    -u $(id -u kg281):$(id -g kg281) \
    -v $INPUT_FOLDER:/data \
    3dtrees_potree_threads \
    python /src/run.py \
    --source /data/ \
    --numthreads ${NUMTHREADS} \
    --outdir output_potree_singles
