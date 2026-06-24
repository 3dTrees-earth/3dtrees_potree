from __future__ import annotations

import json
import logging
import math
import struct
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence

logger = logging.getLogger(__name__)

_WORKER_ATTRIBUTES: Sequence["AttributeInfo"] = ()
_WORKER_INCLUDE_ATTRIBUTES: Optional[frozenset[str]] = None
_WORKER_OCTREE_PATH: Optional[str] = None
_WORKER_ENCODING = "UNCOMPRESSED"

SIDECAR_FILENAME = "attribute_node_stats.json"
MAX_CATEGORICAL_VALUES = 256
HIERARCHY_BYTES_PER_NODE = 22

SKIPPED_ATTRIBUTES = {
    "position",
    "POSITION_CARTESIAN",
    "rgb",
    "rgba",
    "RGBA",
    "COLOR_PACKED",
    "NORMAL",
    "NORMALS",
    "NormalX",
    "NormalY",
    "NormalZ",
    "INDICES",
    "SPACING",
}

TYPE_FORMATS = {
    "int8": ("b", 1, True),
    "uint8": ("B", 1, True),
    "int16": ("h", 2, True),
    "uint16": ("H", 2, True),
    "int32": ("i", 4, True),
    "uint32": ("I", 4, True),
    "int64": ("q", 8, True),
    "uint64": ("Q", 8, True),
    "float": ("f", 4, False),
    "double": ("d", 8, False),
}


@dataclass
class AttributeInfo:
    name: str
    type_name: str
    num_elements: int
    byte_size: int
    is_integer: bool


@dataclass
class Node:
    name: str
    node_type: int = -1
    num_points: int = 0
    byte_offset: int = 0
    byte_size: int = 0
    hierarchy_byte_offset: int = 0
    hierarchy_byte_size: int = 0
    children: List["Node"] = field(default_factory=list)


@dataclass
class AttributeStats:
    is_integer: bool
    min_value: Optional[float] = None
    max_value: Optional[float] = None
    values: Optional[set[int]] = field(default_factory=set)

    def add(self, value: float) -> None:
        if not math.isfinite(float(value)):
            return

        if self.min_value is None or value < self.min_value:
            self.min_value = value
        if self.max_value is None or value > self.max_value:
            self.max_value = value

        if self.values is not None:
            if self.is_integer:
                self.values.add(int(value))
                if len(self.values) > MAX_CATEGORICAL_VALUES:
                    self.values = None
            else:
                self.values = None

    def merge(self, other: "AttributeStats") -> None:
        if other.min_value is not None:
            self.add(other.min_value)
        if other.max_value is not None:
            self.add(other.max_value)

        if self.values is None or other.values is None:
            self.values = None
            return

        self.values.update(other.values)
        if len(self.values) > MAX_CATEGORICAL_VALUES:
            self.values = None

    def to_json(self) -> Dict[str, Any]:
        result: Dict[str, Any] = {}
        if self.min_value is not None and self.max_value is not None:
            result["min"] = _json_number(self.min_value)
            result["max"] = _json_number(self.max_value)
        if self.values:
            result["values"] = sorted(self.values)
        return result


def write_attribute_node_stats_for_outdir(
    outdir: Path,
    *,
    workers: int = 1,
    include_attributes: Optional[set[str]] = None,
) -> List[Path]:
    """Write subtree attribute summaries beside every Potree metadata.json under outdir."""

    metadata_paths = sorted(path for path in outdir.rglob("metadata.json") if path.is_file())
    written: List[Path] = []

    for metadata_path in metadata_paths:
        try:
            written.append(
                write_attribute_node_stats(
                    metadata_path,
                    workers=workers,
                    include_attributes=include_attributes,
                )
            )
        except Exception:
            logger.exception("Failed to write Potree attribute node stats for %s", metadata_path)
            raise

    if not metadata_paths:
        logger.warning("No metadata.json found under %s; skipped attribute node stats sidecar.", outdir)

    return written


def write_attribute_node_stats(
    metadata_path: Path,
    *,
    workers: int = 1,
    include_attributes: Optional[set[str]] = None,
) -> Path:
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    potree_dir = metadata_path.parent
    hierarchy_path = potree_dir / "hierarchy.bin"
    octree_path = potree_dir / "octree.bin"

    if not hierarchy_path.exists() or not octree_path.exists():
        raise FileNotFoundError(f"Expected hierarchy.bin and octree.bin beside {metadata_path}")

    attributes = parse_attributes(metadata.get("attributes", []))
    root = load_hierarchy_tree(metadata, hierarchy_path)
    encoding = str(metadata.get("encoding", "UNCOMPRESSED")).upper()
    subtree_stats, skipped_nodes = build_subtree_stats(
        root,
        attributes,
        octree_path,
        encoding,
        workers=workers,
        include_attributes=include_attributes,
    )

    sidecar = {
        "version": 1,
        "scope": "subtree",
        "source": {
            "metadata": metadata_path.name,
            "hierarchy": hierarchy_path.name,
            "octree": octree_path.name,
            "encoding": encoding,
        },
        "skippedNodes": skipped_nodes,
        "attributes": [
            attribute.name
            for attribute in attributes
            if should_scan_attribute(attribute, include_attributes=include_attributes)
        ],
        "nodes": {
            node_name: {
                attr_name: stats.to_json()
                for attr_name, stats in sorted(node_stats.items())
                if stats.to_json()
            }
            for node_name, node_stats in sorted(subtree_stats.items())
        },
    }

    sidecar["nodes"] = {name: stats for name, stats in sidecar["nodes"].items() if stats}

    output_path = potree_dir / SIDECAR_FILENAME
    output_path.write_text(json.dumps(sidecar, separators=(",", ":"), sort_keys=True) + "\n", encoding="utf-8")
    logger.info("Wrote Potree attribute node stats sidecar: %s", output_path)
    return output_path


def parse_attributes(json_attributes: Sequence[Mapping[str, Any]]) -> List[AttributeInfo]:
    attributes: List[AttributeInfo] = []
    for raw_attribute in json_attributes:
        attribute_name = str(raw_attribute.get("name", ""))
        type_name = str(raw_attribute.get("type", "")).lower()
        type_info = TYPE_FORMATS.get(type_name)
        if type_info is None:
            logger.debug("Skipping unsupported Potree attribute type %s for %s", type_name, raw_attribute.get("name"))
            continue

        num_elements = int(raw_attribute.get("numElements", 1))
        element_size = int(raw_attribute.get("elementSize", type_info[1]))
        byte_size = int(raw_attribute.get("size", num_elements * element_size))
        attributes.append(
            AttributeInfo(
                name=str(raw_attribute.get("name", "")),
                type_name=type_name,
                num_elements=num_elements,
                byte_size=byte_size,
                is_integer=type_info[2],
            )
        )
    return attributes


def load_hierarchy_tree(metadata: Mapping[str, Any], hierarchy_path: Path) -> Node:
    first_chunk_size = int(metadata.get("hierarchy", {}).get("firstChunkSize", 0))
    if first_chunk_size <= 0:
        raise ValueError(f"metadata.json has invalid hierarchy.firstChunkSize: {first_chunk_size}")

    hierarchy_data = hierarchy_path.read_bytes()
    root = Node("r", node_type=2, hierarchy_byte_offset=0, hierarchy_byte_size=first_chunk_size)
    parse_hierarchy_chunk(root, hierarchy_data, 0, first_chunk_size)

    pending = collect_proxy_nodes(root)
    while pending:
        proxy = pending.pop()
        before = len(pending)
        parse_hierarchy_chunk(proxy, hierarchy_data, proxy.hierarchy_byte_offset, proxy.hierarchy_byte_size)
        pending.extend(collect_proxy_nodes(proxy))
        if len(pending) == before and proxy.node_type == 2:
            raise ValueError(f"Proxy node {proxy.name} did not resolve to a real hierarchy chunk")

    return root


def collect_proxy_nodes(root: Node) -> List[Node]:
    proxies: List[Node] = []
    stack = list(root.children)
    while stack:
        node = stack.pop()
        if node.node_type == 2:
            proxies.append(node)
        else:
            stack.extend(node.children)
    return proxies


def parse_hierarchy_chunk(node: Node, hierarchy_data: bytes, byte_offset: int, byte_size: int) -> None:
    chunk = hierarchy_data[byte_offset : byte_offset + byte_size]
    if len(chunk) % HIERARCHY_BYTES_PER_NODE != 0:
        raise ValueError(f"Invalid hierarchy chunk size for node {node.name}: {len(chunk)}")

    nodes: List[Node] = [node]
    for index in range(len(chunk) // HIERARCHY_BYTES_PER_NODE):
        current = nodes[index]
        offset = index * HIERARCHY_BYTES_PER_NODE
        node_type, child_mask, num_points, data_offset, data_size = struct.unpack_from("<BBIqq", chunk, offset)

        if current.node_type == 2:
            current.byte_offset = data_offset
            current.byte_size = data_size
            current.num_points = num_points
        elif node_type == 2:
            current.hierarchy_byte_offset = data_offset
            current.hierarchy_byte_size = data_size
            current.num_points = num_points
        else:
            current.byte_offset = data_offset
            current.byte_size = data_size
            current.num_points = num_points

        if current.byte_size == 0:
            current.num_points = 0

        current.node_type = node_type
        current.children = []

        if current.node_type == 2:
            continue

        for child_index in range(8):
            if child_mask & (1 << child_index):
                child = Node(f"{current.name}{child_index}")
                current.children.append(child)
                nodes.append(child)


def build_subtree_stats(
    root: Node,
    attributes: Sequence[AttributeInfo],
    octree_path: Path,
    encoding: str,
    *,
    workers: int = 1,
    include_attributes: Optional[set[str]] = None,
) -> tuple[Dict[str, Dict[str, AttributeStats]], List[str]]:
    own_stats: Dict[str, Optional[Dict[str, AttributeStats]]] = {}
    skipped_nodes: List[str] = []
    nodes = list(iter_nodes(root))
    if workers > 1:
        logger.info("Scanning %s Potree nodes with %s workers", len(nodes), workers)
        tasks = [(node.name, node.num_points, node.byte_offset, node.byte_size) for node in nodes]
        with ProcessPoolExecutor(
            max_workers=workers,
            initializer=init_scan_worker,
            initargs=(str(octree_path), list(attributes), encoding, include_attributes),
        ) as executor:
            completed = 0
            chunk_size = max(1, len(tasks) // (workers * 16))
            for node_name, stats, error in executor.map(scan_node_task, tasks, chunksize=chunk_size):
                completed += 1
                if completed % 10000 == 0:
                    logger.info("Scanned %s/%s Potree nodes", completed, len(nodes))
                if error is not None:
                    logger.warning("Skipping incomplete Potree sidecar stats for node %s: %s", node_name, error)
                    own_stats[node_name] = None
                    skipped_nodes.append(node_name)
                else:
                    own_stats[node_name] = stats
    else:
        with octree_path.open("rb") as octree_file:
            for node in nodes:
                try:
                    own_stats[node.name] = scan_node_attributes(
                        node,
                        attributes,
                        octree_file,
                        encoding,
                        include_attributes=include_attributes,
                    )
                except Exception as error:
                    logger.warning("Skipping incomplete Potree sidecar stats for node %s: %s", node.name, error)
                    own_stats[node.name] = None
                    skipped_nodes.append(node.name)

    subtree_stats: Dict[str, Dict[str, AttributeStats]] = {}

    def aggregate(node: Node) -> tuple[bool, Dict[str, AttributeStats]]:
        node_own_stats = own_stats.get(node.name, {})
        complete = node_own_stats is not None
        merged = clone_stats_map(node_own_stats or {})
        for child in node.children:
            child_complete, child_merged = aggregate(child)
            complete = complete and child_complete
            for attr_name, child_stats in child_merged.items():
                if attr_name not in merged:
                    merged[attr_name] = AttributeStats(is_integer=child_stats.is_integer)
                merged[attr_name].merge(child_stats)
        if complete:
            subtree_stats[node.name] = merged
        return complete, merged

    aggregate(root)
    return subtree_stats, skipped_nodes


def init_scan_worker(
    octree_path: str,
    attributes: Sequence[AttributeInfo],
    encoding: str,
    include_attributes: Optional[set[str]],
) -> None:
    global _WORKER_ATTRIBUTES, _WORKER_INCLUDE_ATTRIBUTES, _WORKER_OCTREE_PATH, _WORKER_ENCODING
    _WORKER_ATTRIBUTES = attributes
    _WORKER_INCLUDE_ATTRIBUTES = None if include_attributes is None else frozenset(include_attributes)
    _WORKER_OCTREE_PATH = octree_path
    _WORKER_ENCODING = encoding


def scan_node_task(task: tuple[str, int, int, int]) -> tuple[str, Optional[Dict[str, AttributeStats]], Optional[str]]:
    node_name, num_points, byte_offset, byte_size = task
    if _WORKER_OCTREE_PATH is None:
        return node_name, None, "worker was not initialized with an octree path"

    node = Node(name=node_name, num_points=num_points, byte_offset=byte_offset, byte_size=byte_size)
    try:
        with Path(_WORKER_OCTREE_PATH).open("rb") as octree_file:
            stats = scan_node_attributes(
                node,
                _WORKER_ATTRIBUTES,
                octree_file,
                _WORKER_ENCODING,
                include_attributes=_WORKER_INCLUDE_ATTRIBUTES,
            )
        return node_name, stats, None
    except Exception as error:
        return node_name, None, str(error)


def iter_nodes(root: Node) -> Iterable[Node]:
    stack = [root]
    while stack:
        node = stack.pop()
        yield node
        stack.extend(reversed(node.children))


def scan_node_attributes(
    node: Node,
    attributes: Sequence[AttributeInfo],
    octree_file,
    encoding: str,
    *,
    include_attributes: Optional[set[str] | frozenset[str]] = None,
) -> Dict[str, AttributeStats]:
    if node.num_points <= 0 or node.byte_size <= 0:
        return {}

    octree_file.seek(node.byte_offset)
    buffer = octree_file.read(node.byte_size)
    if len(buffer) != node.byte_size:
        raise ValueError(f"Could not read full octree payload for node {node.name}")

    if encoding == "BROTLI":
        try:
            buffer = decompress_brotli(buffer)
        except Exception as error:
            raise ValueError(
                f"Could not decompress BROTLI payload for node {node.name} "
                f"at octree byte range {node.byte_offset}-{node.byte_offset + node.byte_size - 1} "
                f"({node.byte_size} bytes, {node.num_points} points)"
            ) from error
        return scan_brotli_node_buffer(buffer, node, attributes, include_attributes=include_attributes)

    if encoding not in {"UNCOMPRESSED", "DEFAULT"}:
        raise ValueError(f"Unsupported Potree encoding for attribute sidecar: {encoding}")

    return scan_uncompressed_node_buffer(buffer, node, attributes, include_attributes=include_attributes)


def scan_uncompressed_node_buffer(
    buffer: bytes,
    node: Node,
    attributes: Sequence[AttributeInfo],
    *,
    include_attributes: Optional[set[str] | frozenset[str]] = None,
) -> Dict[str, AttributeStats]:
    bytes_per_point = sum(attribute.byte_size for attribute in attributes)
    if bytes_per_point <= 0:
        return {}
    if len(buffer) < node.num_points * bytes_per_point:
        raise ValueError(f"Node {node.name} payload is smaller than expected for {node.num_points} points")

    result: Dict[str, AttributeStats] = {}
    attribute_offset = 0
    for attribute in attributes:
        if should_scan_attribute(attribute, include_attributes=include_attributes):
            stats = AttributeStats(is_integer=attribute.is_integer)
            for point_index in range(node.num_points):
                offset = point_index * bytes_per_point + attribute_offset
                stats.add(read_scalar(buffer, offset, attribute.type_name))
            if stats.min_value is not None:
                result[attribute.name] = stats
        attribute_offset += attribute.byte_size
    return result


def scan_brotli_node_buffer(
    buffer: bytes,
    node: Node,
    attributes: Sequence[AttributeInfo],
    *,
    include_attributes: Optional[set[str] | frozenset[str]] = None,
) -> Dict[str, AttributeStats]:
    result: Dict[str, AttributeStats] = {}
    offset = 0

    for attribute in attributes:
        if attribute.name in {"position", "POSITION_CARTESIAN"}:
            offset += node.num_points * 16
            continue
        if attribute.name in {"rgb", "rgba", "RGBA", "COLOR_PACKED"}:
            offset += node.num_points * 8
            continue

        byte_count = node.num_points * attribute.byte_size
        if offset + byte_count > len(buffer):
            raise ValueError(f"Node {node.name} decoded payload ended while reading {attribute.name}")

        if should_scan_attribute(attribute, include_attributes=include_attributes):
            stats = AttributeStats(is_integer=attribute.is_integer)
            for point_index in range(node.num_points):
                stats.add(read_scalar(buffer, offset + point_index * attribute.byte_size, attribute.type_name))
            if stats.min_value is not None:
                result[attribute.name] = stats

        offset += byte_count

    return result


def should_scan_attribute(
    attribute: AttributeInfo,
    *,
    include_attributes: Optional[set[str] | frozenset[str]] = None,
) -> bool:
    if include_attributes is not None and attribute.name not in include_attributes:
        return False
    return attribute.num_elements == 1 and attribute.name not in SKIPPED_ATTRIBUTES


def read_scalar(buffer: bytes, offset: int, type_name: str) -> float:
    type_info = TYPE_FORMATS[type_name]
    return struct.unpack_from("<" + type_info[0], buffer, offset)[0]


def decompress_brotli(buffer: bytes) -> bytes:
    try:
        import brotli
    except ImportError as error:
        raise RuntimeError(
            "Generating attribute_node_stats.json for BROTLI Potree output requires the Python brotli package."
        ) from error

    return brotli.decompress(buffer)


def clone_stats_map(stats_map: Mapping[str, AttributeStats]) -> Dict[str, AttributeStats]:
    cloned: Dict[str, AttributeStats] = {}
    for name, stats in stats_map.items():
        copy = AttributeStats(is_integer=stats.is_integer)
        copy.min_value = stats.min_value
        copy.max_value = stats.max_value
        copy.values = None if stats.values is None else set(stats.values)
        cloned[name] = copy
    return cloned


def _json_number(value: float) -> int | float:
    if isinstance(value, int):
        return value
    if float(value).is_integer():
        return int(value)
    return float(value)
