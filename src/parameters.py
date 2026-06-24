from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field, AliasChoices
from pathlib import Path
from typing import Optional, List


class Parameters(BaseSettings):
    """CLI parameters for PotreeConverter"""
    
    # Required parameters
    source: List[str] = Field(
        ..., 
        description="Input file(s) or directory containing LAS/LAZ files",
        alias=AliasChoices("source", "i")
    )
    
    # Optional parameters
    outdir: Optional[Path] = Field(
        None,
        description="Output directory (auto-generated if not provided)",
        alias=AliasChoices("outdir", "o", "output-dir", "output_dir")
    )
    
    encoding: str = Field(
        "BROTLI",
        description="Encoding type: 'BROTLI', 'UNCOMPRESSED', 'DEFAULT'"
    )
    
    method: str = Field(
        "poisson",
        description="Point sampling method: 'poisson', 'poisson_average', 'random'",
        alias=AliasChoices("method", "m")
    )
    
    chunkMethod: str = Field(
        "LASZIP",
        description="Chunking method",
        alias=AliasChoices("chunk-method", "chunk_method", "chunkMethod")
    )
    
    attributes: List[str] = Field(
        default_factory=list,
        description="Attributes in output file"
    )

    special_coloring: bool = Field(
        False,
        description="Add Julian-style instance coloring as a coloring_id extra dimension before conversion",
        alias=AliasChoices("special-coloring", "special_coloring")
    )

    special_coloring_palette: str = Field(
        "candy",
        description="Special coloring palette name or comma-separated #RRGGBB color list",
        alias=AliasChoices("special-coloring-palette", "special_coloring_palette", "special-coloring-col", "special_coloring_col")
    )

    special_coloring_n_colors: int = Field(
        10,
        ge=1,
        description="Number of non-ground coloring IDs to generate",
        alias=AliasChoices("special-coloring-n-colors", "special_coloring_n_colors", "special-coloring-n-col", "special_coloring_n_col")
    )

    special_coloring_n_neighbors: int = Field(
        10,
        ge=1,
        description="Number of nearest instance centroids used for neighbor-aware color assignment",
        alias=AliasChoices("special-coloring-n-neighbors", "special_coloring_n_neighbors")
    )

    special_coloring_instance_attribute: str = Field(
        "PredInstance",
        description="Point attribute containing instance IDs for special coloring",
        alias=AliasChoices("special-coloring-instance-attribute", "special_coloring_instance_attribute", "special-coloring-instance-id", "special_coloring_instance_id")
    )

    special_coloring_ground_id: int = Field(
        0,
        description="Instance ID treated as ground/background for special coloring",
        alias=AliasChoices("special-coloring-ground-id", "special_coloring_ground_id")
    )

    special_coloring_ground_color: str = Field(
        "#808080",
        description="Ground/background color for special coloring as #RRGGBB",
        alias=AliasChoices("special-coloring-ground-color", "special_coloring_ground_color")
    )

    special_coloring_sidecar_json: bool = Field(
        False,
        description="Write special_coloring_mapping.json and patch generated Potree HTML viewers to use it",
        alias=AliasChoices(
            "special-coloring-sidecar-json",
            "special_coloring_sidecar_json",
            "special-coloring-mapping-json",
            "special_coloring_mapping_json",
        )
    )

    attribute_node_stats: bool = Field(
        True,
        description="Write attribute_node_stats.json beside generated Potree metadata.json files for fast frontend filtering",
        alias=AliasChoices("attribute-node-stats", "attribute_node_stats")
    )
    
    # Boolean flags
    keep_chunks: bool = Field(
        False,
        description="Skip deleting temporary chunks during conversion",
        alias=AliasChoices("keep-chunks", "keep_chunks")
    )
    
    no_chunking: bool = Field(
        False,
        description="Disable chunking phase",
        alias=AliasChoices("no-chunking", "no_chunking")
    )
    
    no_indexing: bool = Field(
        False,
        description="Disable indexing phase",
        alias=AliasChoices("no-indexing", "no_indexing")
    )

    numthreads: int = Field(
        0,
        description="Override detected CPU count / worker thread count (0 = auto)",
        alias=AliasChoices("numthreads", "num-threads", "num_threads")
    )

    grid_size: int = Field(
        0,
        description="Grid size for chunking phase (0 = auto: 128 for <100M pts, 256 for <500M, 512 for larger)",
        alias=AliasChoices("grid-size", "grid_size", "gridSize")
    )
    
    # Page generation
    generate_page: Optional[str] = Field(
        None,
        description="Generate a ready-to-use web page with the given name",
        alias=AliasChoices("generate-page", "generate_page", "p")
    )
    
    title: Optional[str] = Field(
        None,
        description="Page title used when generating a web page"
    )

    model_config = SettingsConfigDict(
        case_sensitive=False,
        cli_parse_args=True,
        cli_ignore_unknown_args=False
    )
