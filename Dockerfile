# Dockerfile for PotreeConverter with Python wrapper
# Builds PotreeConverter from source with patches for:
#   - duplicate attribute names, UTF-8 error handling, classification lookup
#   - memory leak fix (PR #666): removes parallel sort to prevent TBB memory leak
#   - numthreads override (PR #575-inspired): cap detected CPU count / workers
#   - --grid-size CLI option: override auto-detected chunking grid resolution

FROM python:3.11-slim AS builder

# Install build dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    git \
    cmake \
    build-essential \
    libtbb-dev \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Clone PotreeConverter source
WORKDIR /opt
RUN git clone --depth 1 --branch 2.1.1 https://github.com/potree/PotreeConverter.git potree_source

# Copy and apply patches (duplicate attribute names, UTF-8)
COPY patches/ /opt/patches/
WORKDIR /opt/potree_source
# PotreeConverter 2.1.1 has CRLF in some files; patches are LF
RUN sed -i 's/\r$//' Converter/include/PotreeConverter.h && \
    git apply -p1 /opt/patches/duplicate_attributes_keep.patch
RUN sed -i 's/\r$//' Converter/include/Attributes.h Converter/src/chunker_countsort_laszip.cpp && \
    git apply -p1 /opt/patches/chunker_classification_lookup.patch
RUN sed -i 's/string content = js\.dump(4);/string content = js.dump(4, '\'' '\'', false, json::error_handler_t::replace);/' \
    Converter/src/chunker_countsort_laszip.cpp
# Fix TBB memory leak by removing parallel sort (https://github.com/potree/PotreeConverter/pull/666)
RUN sed -i 's/\r$//' Converter/include/sampler_poisson.h Converter/include/sampler_poisson_average.h && \
    git apply -p1 /opt/patches/fix_memory_leak_parallel_sort.patch
# Add --numthreads CLI option to cap detected CPU count / worker threads
RUN sed -i 's/\r$//' \
        Converter/include/converter_utils.h \
        Converter/modules/unsuck/unsuck.hpp \
        Converter/modules/unsuck/unsuck_platform_specific.cpp \
        Converter/src/main.cpp && \
    git apply -p1 /opt/patches/numthreads.patch

# Add --grid-size CLI option to override auto-detected chunking grid resolution
RUN sed -i 's/\r$//' Converter/include/converter_utils.h \
        Converter/include/chunker_countsort_laszip.h \
        Converter/src/chunker_countsort_laszip.cpp \
        Converter/src/main.cpp && \
    # 1) Add gridSize field to Options struct
    sed -i '/bool noIndexing/a\\tint gridSize = 0;' \
        Converter/include/converter_utils.h && \
    # 2) Add gridSizeOverride parameter to doChunking declaration
    sed -i 's/Attributes outputAttributes, Monitor\* monitor);/Attributes outputAttributes, Monitor* monitor, int gridSizeOverride = 0);/' \
        Converter/include/chunker_countsort_laszip.h && \
    # 3) Add gridSizeOverride parameter to doChunking definition
    sed -i "s/Attributes outputAttributes, Monitor\* monitor) {/Attributes outputAttributes, Monitor* monitor, int gridSizeOverride) {/" \
        Converter/src/chunker_countsort_laszip.cpp && \
    # 4) Use override value when provided, otherwise keep auto-detection
    sed -i "s/if (state.pointsTotal < 100'000'000)/if (gridSizeOverride > 0) {\n\t\tgridSize = gridSizeOverride;\n\t} else if (state.pointsTotal < 100'000'000)/" \
        Converter/src/chunker_countsort_laszip.cpp && \
    # 5) Register --grid-size CLI argument
    sed -i '/args.addArgument("title"/a\\targs.addArgument("grid-size", "Grid size for chunking (default: auto based on point count)");' \
        Converter/src/main.cpp && \
    # 6) Parse --grid-size value (match unique assignment in parseArguments)
    sed -i '/bool noIndexing = args.has/a\\tint gridSize = args.get("grid-size").as<int>(0);' \
        Converter/src/main.cpp && \
    # 7) Set options.gridSize (match unique assignment in parseArguments)
    sed -i '/options.noIndexing = noIndexing/a\\toptions.gridSize = gridSize;' \
        Converter/src/main.cpp && \
    # 8) Pass gridSize through chunking() to doChunking()
    sed -i 's/state, outputAttributes, monitor);/state, outputAttributes, monitor, options.gridSize);/' \
        Converter/src/main.cpp

# Build PotreeConverter
WORKDIR /opt/potree_source/build
RUN cmake -DCMAKE_BUILD_TYPE=Release .. \
    && make -j$(nproc) \
    && mkdir -p /opt/PotreeConverter \
    && cp PotreeConverter /opt/PotreeConverter/ \
    && cp liblaszip.so /opt/PotreeConverter/ \
    && (cp -r ../resources /opt/PotreeConverter/ 2>/dev/null || true)

# Runtime stage
FROM python:3.11-slim

# Install only runtime dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    libtbb12 \
    && rm -rf /var/lib/apt/lists/*

# Copy built PotreeConverter from builder stage
COPY --from=builder /opt/PotreeConverter /opt/PotreeConverter
RUN chmod +x /opt/PotreeConverter/PotreeConverter

# Add to PATH and set library path
ENV PATH="/opt/PotreeConverter:${PATH}"
ENV LD_LIBRARY_PATH="/opt/PotreeConverter"

# Install Python dependencies
RUN pip install --no-cache-dir \
    laspy \
    lazrs \
    numpy \
    pydantic \
    pydantic-settings \
    scikit-learn

ENV LANG=en_US.utf-8
ENV LC_ALL=en_US.utf-8

# Copy Python wrapper scripts
COPY src/ /src/
RUN chmod -R a+rX /src
COPY src/libs /data/output/libs

# Default working directory for point cloud data
WORKDIR /data
