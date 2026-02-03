# Slim Dockerfile for PotreeConverter with Python wrapper
# Downloads pre-built binary from GitHub releases and wraps it with Python

FROM python:3.11-slim

# Install only essential runtime dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    wget \
    unzip \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Download and extract PotreeConverter
WORKDIR /opt
RUN wget -q https://github.com/potree/PotreeConverter/releases/download/2.1.1/PotreeConverter_2.1.1_x64_linux.zip \
    && unzip -q PotreeConverter_2.1.1_x64_linux.zip \
    && mv PotreeConverter_linux_x64 PotreeConverter \
    && rm PotreeConverter_2.1.1_x64_linux.zip \
    && chmod +x /opt/PotreeConverter/PotreeConverter \
    # Clean up tools no longer needed
    && apt-get purge -y wget unzip \
    && apt-get autoremove -y \
    && rm -rf /var/lib/apt/lists/*

# Add to PATH and set library path
ENV PATH="/opt/PotreeConverter:${PATH}"
ENV LD_LIBRARY_PATH="/opt/PotreeConverter:${LD_LIBRARY_PATH}"

# Install Python dependencies
RUN pip install --no-cache-dir pydantic pydantic-settings

# Copy Python wrapper scripts
COPY src/ /src/

# Default working directory for point cloud data
WORKDIR /data

