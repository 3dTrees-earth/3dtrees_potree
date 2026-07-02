#!/usr/bin/env python3

from __future__ import annotations

import logging
import subprocess
import sys
from functools import lru_cache
from pathlib import Path
from typing import Iterable, List, Optional, Sequence

from parameters import Parameters
from special_coloring import run_special_coloring_conversion

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)
POTREE_CONVERTER = "/opt/PotreeConverter/PotreeConverter"

BOOLEAN_FLAGS = {
    "--keep-chunks",
    "--keep_chunks",
    "--no-chunking",
    "--no_chunking",
    "--no-indexing",
    "--no_indexing",
    "--special-coloring",
    "--special_coloring",
    "--special-coloring-sidecar-json",
    "--special_coloring_sidecar_json",
    "--special-coloring-mapping-json",
    "--special_coloring_mapping_json",
}


def expand_boolean_flags(argv: Sequence[str]) -> List[str]:
    return [f"{arg}=true" if arg in BOOLEAN_FLAGS else arg for arg in argv]


def normalize_attributes(attributes: Optional[Iterable[str]]) -> List[str]:
    normalized: List[str] = []
    seen = set()
    for value in attributes or []:
        for part in str(value).split(","):
            attr = part.strip()
            key = attr.lower()
            if attr and key not in seen:
                seen.add(key)
                normalized.append(attr)
    return normalized


def resolve_special_coloring_instance_attributes(params: Parameters) -> List[str]:
    if params.special_coloring_instance_attribute:
        return normalize_attributes([params.special_coloring_instance_attribute])
    return normalize_attributes(params.special_coloring_instance_attributes)


def build_potree_command(
    params: Parameters,
    *,
    sources: Optional[Sequence[str]] = None,
    attributes: Optional[Sequence[str]] = None,
) -> List[str]:
    command = [POTREE_CONVERTER, *(sources or params.source)]
    if params.outdir:
        command.extend(["-o", str(params.outdir)])
    if params.encoding != "DEFAULT":
        command.extend(["--encoding", params.encoding])
    if params.method != "poisson":
        command.extend(["-m", params.method])
    if params.chunkMethod != "LASZIP":
        command.extend(["--chunkMethod", params.chunkMethod])
    for attr in normalize_attributes(attributes if attributes is not None else params.attributes):
        command.extend(["--attributes", attr])
    if params.keep_chunks:
        command.append("--keep-chunks")
    if params.no_chunking:
        command.append("--no-chunking")
    if params.no_indexing:
        command.append("--no-indexing")
    if params.numthreads > 0 and converter_supports_argument("--numthreads"):
        command.extend(["--numthreads", str(params.numthreads)])
    elif params.numthreads > 0:
        logger.warning("Ignoring --numthreads because this PotreeConverter binary does not support it.")
    if params.grid_size > 0 and converter_supports_argument("--grid-size"):
        command.extend(["--grid-size", str(params.grid_size)])
    elif params.grid_size > 0:
        logger.warning("Ignoring --grid-size because this PotreeConverter binary does not support it.")
    if params.generate_page:
        command.extend(["-p", params.generate_page])
    if params.title:
        command.extend(["--title", params.title])
    return command


@lru_cache(maxsize=1)
def potree_converter_help() -> str:
    result = subprocess.run(
        [POTREE_CONVERTER, "--help"],
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    return result.stdout


def converter_supports_argument(argument: str) -> bool:
    return argument in potree_converter_help()


def run_command(command: Sequence[str]) -> str:
    logger.info("Executing: %s", " ".join(command))
    return subprocess.run(
        list(command),
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    ).stdout


def run(params: Parameters) -> str:
    if not params.special_coloring:
        return run_command(build_potree_command(params))

    params.outdir = params.outdir or Path("output")
    return run_special_coloring_conversion(
        sources=params.source,
        outdir=params.outdir,
        attributes=params.attributes,
        instance_attributes=resolve_special_coloring_instance_attributes(params),
        palette_name=params.special_coloring_palette,
        n_colors=params.special_coloring_n_colors,
        n_neighbors=params.special_coloring_n_neighbors,
        ground_instance_id=params.special_coloring_ground_id,
        ground_color=params.special_coloring_ground_color,
        write_sidecar_json=params.special_coloring_sidecar_json,
        generate_page=params.generate_page,
        build_command=lambda sources, attributes: build_potree_command(
            params,
            sources=sources,
            attributes=attributes,
        ),
        run_command=run_command,
    )


def main() -> int:
    try:
        sys.argv = [sys.argv[0], *expand_boolean_flags(sys.argv[1:])]
        print(run(Parameters()))
        logger.info("PotreeConverter completed successfully")
        return 0
    except subprocess.CalledProcessError as error:
        logger.error("PotreeConverter failed with exit code %s", error.returncode)
        logger.error("Output: %s", error.stdout)
        return error.returncode
    except Exception as error:
        logger.error("Error: %s", error)
        return 1


if __name__ == "__main__":
    sys.exit(main())
