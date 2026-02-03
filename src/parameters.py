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
