# Dockerfile for PotreeConverter with Python wrapper
# Builds PotreeConverter from source with UTF-8 error handling patch

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

# Apply UTF-8 error handling patch
WORKDIR /opt/potree_source
RUN sed -i 's/string content = js\.dump(4);/string content = js.dump(4, '\'' '\'', false, json::error_handler_t::replace);/' \
    Converter/src/chunker_countsort_laszip.cpp

# Build PotreeConverter
WORKDIR /opt/potree_source/build
RUN cmake -DCMAKE_BUILD_TYPE=Release .. \
    && make -j$(nproc) \
    && mkdir -p /opt/PotreeConverter \
    && cp PotreeConverter /opt/PotreeConverter/ \
    && cp liblaszip.so /opt/PotreeConverter/ \
    && cp -r ../resources /opt/PotreeConverter/ 2>/dev/null || true

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
ENV LD_LIBRARY_PATH="/opt/PotreeConverter:${LD_LIBRARY_PATH}"

# Install Python dependencies
RUN pip install --no-cache-dir pydantic pydantic-settings

ENV LANG=en_US.utf-8
ENV LC_ALL=en_US.utf-8

# Copy Python wrapper scripts
COPY src/ /src/
COPY src/libs /data/output/libs

# Default working directory for point cloud data
WORKDIR /data