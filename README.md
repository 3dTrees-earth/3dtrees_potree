# PotreeConverter Python Wrapper

A Python wrapper for [PotreeConverter](https://github.com/potree/PotreeConverter) that provides a clean CLI interface using Pydantic for parameter validation. This wrapper makes it easy to convert LAS/LAZ point cloud files into Potree's octree format for web-based visualization.

## About PotreeConverter

PotreeConverter generates an octree LOD structure for streaming and real-time rendering of massive point clouds. The results can be viewed in web browsers with [Potree](https://github.com/potree/potree).

**Original Repository:** https://github.com/potree/PotreeConverter

## Features

- ✅ **All PotreeConverter parameters exposed** - Full access to all 11 CLI options
- ✅ **Type-safe parameter validation** - Using Pydantic for robust input validation
- ✅ **Multiple parameter aliases** - Supports both Python-style (`--output_dir`) and CLI-style (`--output-dir`) naming
- ✅ **Slim Docker image** - ~200-250MB using Python 3.11-slim base
- ✅ **Pre-built binary** - Uses official PotreeConverter 2.1.1 release from GitHub
- ✅ **Comprehensive logging** - Detailed execution logs with timestamps

## Quick Start

### Build the Docker Image

```bash
docker build -t 3dtrees_potree .
```

### Basic Usage

Convert a single LAS/LAZ file:

```bash
docker run --rm -v /path/to/data:/data 3dtrees_potree \
  --source /data/input.las \
  --outdir /data/output
```

Convert all files in a directory:

```bash
docker run --rm -v /path/to/data:/data 3dtrees_potree \
  --source /data/input_dir \
  --outdir /data/output
```

## Available Parameters

| Parameter | Alias | Type | Default | Description |
|-----------|-------|------|---------|-------------|
| `--source` | `-i` | List[str] | *required* | Input file(s) or directory containing LAS/LAZ files |
| `--outdir` | `-o` | Path | *auto-generated* | Output directory |
| `--encoding` | | str | `DEFAULT` | Encoding type: `BROTLI`, `UNCOMPRESSED`, `DEFAULT` |
| `--method` | `-m` | str | `poisson` | Sampling method: `poisson`, `poisson_average`, `random` |
| `--chunk-method` | | str | `LASZIP` | Chunking method |
| `--attributes` | | List[str] | `[]` | Attributes in output file |
| `--keep-chunks` | | bool | `False` | Skip deleting temporary chunks |
| `--no-chunking` | | bool | `False` | Disable chunking phase |
| `--no-indexing` | | bool | `False` | Disable indexing phase |
| `--generate-page` | `-p` | str | `None` | Generate web page with given name |
| `--title` | | str | `None` | Page title for generated web page |

## Usage Examples

### With Custom Sampling Method

```bash
docker run --rm -v /path/to/data:/data 3dtrees_potree \
  --source /data/input.las \
  --outdir /data/output \
  --method poisson_average
```

### With BROTLI Compression

```bash
docker run --rm -v /path/to/data:/data 3dtrees_potree \
  --source /data/input.las \
  --outdir /data/output \
  --encoding BROTLI
```

### Multiple Input Files

```bash
docker run --rm -v /path/to/data:/data 3dtrees_potree \
  --source /data/file1.las /data/file2.las /data/file3.las \
  --outdir /data/output
```

### Generate Web Viewer Page

```bash
docker run --rm -v /path/to/data:/data 3dtrees_potree \
  --source /data/input.las \
  --outdir /data/output \
  --generate-page mycloud \
  --title "My Point Cloud Visualization"
```

### Advanced: Custom Attributes and Flags

```bash
docker run --rm -v /path/to/data:/data 3dtrees_potree \
  --source /data/input.las \
  --outdir /data/output \
  --method random \
  --encoding BROTLI \
  --attributes intensity classification \
  --keep-chunks
```

### View Help

```bash
docker run --rm 3dtrees_potree --help
```

## Project Structure

```
.
├── Dockerfile              # Docker image definition
├── src/
│   ├── parameters.py       # Pydantic parameter definitions
│   └── run.py             # Main execution script
└── README.md              # This file
```

## How It Works

1. **parameters.py** - Defines all PotreeConverter parameters using Pydantic's `BaseSettings` class with CLI argument parsing
2. **run.py** - Parses CLI arguments, builds the PotreeConverter command, and executes it via subprocess
3. **Dockerfile** - Creates a slim image with Python 3.11, PotreeConverter binary, and Python dependencies

## Performance

**Tested with:** 1.6M points, 10.5 MB LAZ file  
**Conversion time:** ~5 seconds  
**Throughput:** ~0.3M points/second  
**Memory usage:** ~8GB peak

Performance scales with input size and available CPU cores (automatically uses all available threads).

## Output Format

PotreeConverter 2.0 produces:
- **3 files total** (instead of thousands in v1.7)
- Octree LOD structure for efficient streaming
- Compatible with Potree 1.7+ viewer
- Optional web page with embedded viewer

## Requirements

- Docker
- Input: LAS/LAZ point cloud files
- Sufficient disk space for output (typically similar to input size)

## License

This wrapper is provided as-is. PotreeConverter itself is licensed under the [BSD 2-clause license](https://github.com/potree/PotreeConverter/blob/master/LICENSE).

## References

- **PotreeConverter:** https://github.com/potree/PotreeConverter
- **Potree Viewer:** https://github.com/potree/potree
- **Paper:** [Fast Out-of-Core Octree Generation for Massive Point Clouds](https://www.cg.tuwien.ac.at/research/publications/2020/SCHUETZ-2020-MPC/)

## Troubleshooting

### Permission Issues

Ensure the mounted volume has proper permissions:

```bash
chmod -R 755 /path/to/data
```

### Out of Memory

For very large point clouds, ensure Docker has sufficient memory allocated (8GB+ recommended).

### File Not Found

Make sure to use absolute paths and verify the file exists in the mounted volume:

```bash
ls -la /path/to/data/
```
