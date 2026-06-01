# PotreeConverter Python Wrapper

A Python wrapper for [PotreeConverter](https://github.com/potree/PotreeConverter) that provides a clean CLI interface using Pydantic for parameter validation. This wrapper makes it easy to convert LAS/LAZ point cloud files into Potree's octree format for web-based visualization.

## About PotreeConverter

PotreeConverter generates an octree LOD structure for streaming and real-time rendering of massive point clouds. The results can be viewed in web browsers with [Potree](https://github.com/potree/potree).

**Original Repository:** https://github.com/potree/PotreeConverter

## Features

- ✅ **Core PotreeConverter parameters exposed** - Conversion, sampling, encoding, attributes, and page generation
- ✅ **Type-safe parameter validation** - Using Pydantic for robust input validation
- ✅ **Multiple parameter aliases** - Supports both Python-style (`--output_dir`) and CLI-style (`--output-dir`) naming
- ✅ **Slim Docker image** - ~200-250MB using Python 3.11-slim base
- ✅ **Pre-built binary** - Uses official PotreeConverter 2.1.1 release from GitHub
- ✅ **Special instance coloring** - Adds optional neighbor-aware `coloring_id` values while preserving source RGB
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
  python /src/run.py \
  --source /data/input.las \
  --outdir /data/output
```

Convert all files in a directory:

```bash
docker run --rm -v /path/to/data:/data 3dtrees_potree \
  python /src/run.py \
  --source /data/input_dir \
  --outdir /data/output
```

## Available Parameters

| Parameter | Alias | Type | Default | Description |
|-----------|-------|------|---------|-------------|
| `--source` | `-i` | List[str] | *required* | Input file(s) or directory containing LAS/LAZ files |
| `--outdir` | `-o` | Path | *auto-generated* | Output directory |
| `--encoding` | | str | `BROTLI` | Encoding type: `BROTLI`, `UNCOMPRESSED`, `DEFAULT` |
| `--method` | `-m` | str | `poisson` | Sampling method: `poisson`, `poisson_average`, `random` |
| `--chunk-method` | | str | `LASZIP` | Chunking method |
| `--attributes` | | List[str] | `[]` | Attributes in output file |
| `--special-coloring` | | bool | `False` | Add a `coloring_id` extra dimension from `PredInstance` |
| `--special-coloring-palette` | | str | `candy` | Palette name or comma-separated `#RRGGBB` colors for special coloring |
| `--special-coloring-n-colors` | | int | `10` | Number of non-ground coloring IDs |
| `--special-coloring-n-neighbors` | | int | `10` | Number of nearest instance centroids used to avoid nearby color collisions |
| `--special-coloring-instance-attribute` | | str | `PredInstance` | Point attribute containing instance IDs |
| `--special-coloring-ground-id` | | int | `0` | Instance ID treated as ground/background; negative instance IDs are also treated as background |
| `--special-coloring-ground-color` | | str | `#808080` | Ground/background color |
| `--special-coloring-sidecar-json` | | bool | `False` | Write `special_coloring_mapping.json` and patch generated Potree HTML viewers to use it |
| `--keep-chunks` | | bool | `False` | Skip deleting temporary chunks |
| `--no-chunking` | | bool | `False` | Disable chunking phase |
| `--no-indexing` | | bool | `False` | Disable indexing phase |
| `--generate-page` | `-p` | str | `None` | Generate web page with given name |
| `--title` | | str | `None` | Page title for generated web page |

## Usage Examples

### With Custom Sampling Method

```bash
docker run --rm -v /path/to/data:/data 3dtrees_potree \
  python /src/run.py \
  --source /data/input.las \
  --outdir /data/output \
  --method poisson_average
```

### With BROTLI Compression

```bash
docker run --rm -v /path/to/data:/data 3dtrees_potree \
  python /src/run.py \
  --source /data/input.las \
  --outdir /data/output \
  --encoding BROTLI
```

### Multiple Input Files

```bash
docker run --rm -v /path/to/data:/data 3dtrees_potree \
  python /src/run.py \
  --source /data/file1.las /data/file2.las /data/file3.las \
  --outdir /data/output
```

### Generate Web Viewer Page

```bash
docker run --rm -v /path/to/data:/data 3dtrees_potree \
  python /src/run.py \
  --source /data/input.las \
  --outdir /data/output \
  --generate-page mycloud \
  --title "My Point Cloud Visualization"
```

### Advanced: Custom Attributes and Flags

```bash
docker run --rm -v /path/to/data:/data 3dtrees_potree \
  python /src/run.py \
  --source /data/input.las \
  --outdir /data/output \
  --method random \
  --encoding BROTLI \
  --attributes intensity classification \
  --keep-chunks
```

### With Special Instance Coloring

Preserve original RGB while adding a display-only `coloring_id` attribute based on the `PredInstance` extra dimension:

```bash
docker run --rm -v /path/to/data:/data 3dtrees_potree \
  python /src/run.py \
  --source /data/input_segmented.laz \
  --outdir /data/output \
  --special-coloring \
  --special-coloring-sidecar-json
```

This adds `coloring_id` to the generated Potree point cloud and does not pass any `--attributes` arguments to PotreeConverter.
When `--special-coloring-sidecar-json` is set, the tool writes `special_coloring_mapping.json` to the output directory, copies it beside generated `metadata.json` files for frontend discovery, and patches generated Potree HTML viewers to use those sidecar colors for `coloring_id`.
`PredInstance` values equal to the ground ID, and negative `PredInstance` values such as `-1`, map to `coloring_id = 0`.

Built-in special coloring palettes are `sky`, `sea`, `cozy`, `fairy`, `winter`, `rainbow`, `pastel`, `candy`, and `boring`.

### View Help

```bash
docker run --rm 3dtrees_potree python /src/run.py --help
```

## Project Structure

```
.
├── Dockerfile              # Docker image definition
├── src/
│   ├── parameters.py       # Pydantic parameter definitions
│   ├── run.py              # Main execution script
│   └── special_coloring.py # Instance coloring preprocessing
├── tests/                  # Unit tests for wrapper logic
└── README.md              # This file
```

## How It Works

1. **parameters.py** - Defines all PotreeConverter parameters using Pydantic's `BaseSettings` class with CLI argument parsing
2. **run.py** - Parses CLI arguments, builds the PotreeConverter command, and executes it via subprocess
3. **Dockerfile** - Creates a slim image with Python 3.11, PotreeConverter binary, and Python dependencies. The image intentionally leaves entrypoint control to callers so Galaxy can launch its generated shell script.

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

With `--special-coloring-sidecar-json`, the output directory also contains:
- **special_coloring_mapping.json**: Mapping from `coloring_id` to RGB/hex colors and from `PredInstance` to `coloring_id`

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
