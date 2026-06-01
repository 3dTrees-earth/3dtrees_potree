from __future__ import annotations

import json
import logging
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

import laspy
import numpy as np

logger = logging.getLogger(__name__)

INSTANCE_ATTRIBUTE = "PredInstance"
COLOR_ATTRIBUTE = "coloring_id"
COLOR_ATTRIBUTE_DTYPE = np.uint16
GROUND_INSTANCE_ID = 0
GROUND_COLORING_ID = 0
GROUND_COLOR_HEX = "#808080"
PALETTE_NAME = "candy"
N_COLORS = 10
N_NEIGHBORS = 10
RANDOM_SEED = 0
CHUNK_SIZE = 2_000_000

PALETTES = {
    "sky": ["#f2c13a", "#ef7239", "#f23184", "#955ae8", "#5c96f5"],
    "sea": ["#d9ed92", "#99d98c", "#52b69a", "#168aad", "#1e6091", "#154366", "#0C304C"],
    "cozy": ["#41764c", "#a7c957", "#eadbb3", "#d68b8b", "#bc4749"],
    "fairy": ["#cd92ef", "#ffadcb", "#fed2e2", "#b1e2fc", "#9bc1ff"],
    "winter": ["#007DA3", "#00afb9", "#fdfcdc", "#fdca9b", "#ee6258"],
    "rainbow": ["#f52e2e", "#f5982e", "#f5d42e", "#dcf636", "#acf636", "#36f6a6", "#36e9f6", "#3d90ee", "#7336f6", "#c236f6"],
    "pastel": ["#fcf7b7", "#fed9bb", "#ffbfc3", "#f7aae7", "#c4a6f5", "#90bbf8", "#7cd9f8", "#7beff9", "#85f9e0", "#a4fdac"],
    "candy": ["#9137ff", "#ff5ce4", "#ff4545", "#fee440", "#00bbf9", "#00f5bc"],
    "boring": ["#DEE2E6", "#191C1F"],
}

SRGB_TO_XYZ = np.array(
    [
        [0.4124564, 0.3575761, 0.1804375],
        [0.2126729, 0.7151522, 0.0721750],
        [0.0193339, 0.1191920, 0.9503041],
    ],
    dtype=np.float64,
)
XYZ_TO_SRGB = np.array(
    [
        [3.2404542, -1.5371385, -0.4985314],
        [-0.9692660, 1.8760108, 0.0415560],
        [0.0556434, -0.2040259, 1.0572252],
    ],
    dtype=np.float64,
)
D65_WHITE = np.array([0.95047, 1.0, 1.08883], dtype=np.float64)


@dataclass
class InstanceStats:
    count: int = 0
    sum_x: float = 0.0
    sum_y: float = 0.0
    sum_z: float = 0.0


@dataclass
class SpecialColoringResult:
    sources: List[str]
    mapping_path: Path
    source_files: List[Path]
    instance_count: int


PotreeCommandBuilder = Callable[[Sequence[str], Sequence[str]], List[str]]
PotreeCommandRunner = Callable[[Sequence[str]], str]


def run_special_coloring_conversion(
    *,
    sources: Sequence[str],
    outdir: Path,
    attributes: Sequence[str],
    instance_attribute: str,
    palette_name: str,
    n_colors: int,
    n_neighbors: int,
    ground_instance_id: int,
    ground_color: str,
    write_sidecar_json: bool,
    generate_page: Optional[str],
    build_command: PotreeCommandBuilder,
    run_command: PotreeCommandRunner,
) -> str:
    outdir.parent.mkdir(parents=True, exist_ok=True)
    if attributes:
        logger.info("Ignoring --attributes because --special-coloring uses PotreeConverter defaults.")

    with tempfile.TemporaryDirectory(prefix="potree_special_coloring_", dir=str(outdir.parent)) as tmp_dir:
        mapping_path = outdir / "special_coloring_mapping.json"
        result = prepare_special_coloring_inputs(
            sources,
            Path(tmp_dir),
            mapping_path,
            instance_attribute=instance_attribute,
            palette_name=palette_name,
            n_colors=n_colors,
            n_neighbors=n_neighbors,
            ground_instance_id=ground_instance_id,
            ground_color=ground_color,
            write_sidecar_json=write_sidecar_json,
        )
        logger.info(
            "Special coloring prepared %s input file(s), %s non-ground instance(s), "
            "instance_attribute=%s, palette=%s, n_colors=%s, n_neighbors=%s, ground_id=%s, sidecar_json=%s, mapping=%s",
            len(result.source_files),
            result.instance_count,
            instance_attribute,
            palette_name,
            n_colors,
            n_neighbors,
            ground_instance_id,
            write_sidecar_json,
            result.mapping_path if write_sidecar_json else None,
        )
        command = build_command(result.sources, [])
        stdout = run_command(command)
        if write_sidecar_json:
            for copied_path in copy_mapping_to_metadata_siblings(outdir, mapping_path):
                logger.info("Copied special coloring mapping beside metadata: %s", copied_path)
            if generate_page:
                patched_html = patch_special_coloring_viewer_html(outdir, generate_page, mapping_path.name)
                if patched_html:
                    logger.info("Patched generated viewer for special coloring sidecar: %s", patched_html)
        return stdout


def copy_mapping_to_metadata_siblings(outdir: Path, mapping_path: Path) -> List[Path]:
    copied_paths: List[Path] = []
    if not mapping_path.exists() or not outdir.exists():
        return copied_paths

    for metadata_path in sorted(outdir.rglob("metadata.json")):
        target_path = metadata_path.parent / mapping_path.name
        if target_path.resolve() == mapping_path.resolve():
            continue
        shutil.copyfile(mapping_path, target_path)
        copied_paths.append(target_path)

    return copied_paths


def patch_special_coloring_viewer_html(outdir: Path, page_name: str, mapping_filename: str) -> Optional[Path]:
    html_path = outdir / f"{page_name}.html"
    if not html_path.exists():
        return None

    html = html_path.read_text(encoding="utf-8")
    marker = "3DTREES_SPECIAL_COLORING_VIEWER_PATCH_V2"
    if marker in html:
        return html_path

    metadata_url = f"./pointclouds/{page_name}/metadata.json"
    load_line = f'Potree.loadPointCloud("{metadata_url}", "{page_name}", e => {{'
    active_attr_line = 'material.activeAttributeName = "rgba";'
    if load_line not in html or active_attr_line not in html:
        logger.warning("Could not patch %s: expected Potree viewer lines not found", html_path)
        return None

    helper = SPECIAL_COLORING_VIEWER_HELPER.format(marker=marker, mapping_filename=mapping_filename)
    patched = html.replace(load_line, helper + "\n\n\t\t" + load_line, 1)
    patched = patched.replace(
        active_attr_line,
        active_attr_line + f'\n\t\t\tapply3DtreesSpecialColoring(pointcloud, "{metadata_url}");',
        1,
    )
    patched = patched.replace(
        "url('../build/potree/resources/images/background.jpg')",
        "url('./libs/potree/resources/images/background.jpg')",
    )
    html_path.write_text(patched, encoding="utf-8")
    return html_path


SPECIAL_COLORING_VIEWER_HELPER = """

\t\tconst THREEDTREES_SPECIAL_COLORING_VIEWER_PATCH = true; // {marker}
\t\tasync function apply3DtreesSpecialColoring(pointcloud, metadataUrl) {{
\t\t\tconst mappingUrl = new URL("{mapping_filename}", new URL(metadataUrl, window.location.href)).href;
\t\t\tlet mapping;
\t\t\ttry {{
\t\t\t\tconst response = await fetch(mappingUrl);
\t\t\t\tif (!response.ok) {{
\t\t\t\t\tconsole.warn(`Special coloring mapping unavailable (${{response.status}}).`);
\t\t\t\t\treturn;
\t\t\t\t}}
\t\t\t\tmapping = await response.json();
\t\t\t}} catch (error) {{
\t\t\t\tconsole.warn("Special coloring mapping could not be loaded.", error);
\t\t\t\treturn;
\t\t\t}}

\t\t\tconst colorAttributeName = mapping.color_attribute || "coloring_id";
\t\t\tconst attributes = pointcloud?.pcoGeometry?.pointAttributes?.attributes || [];
\t\t\tconst attrInfo = attributes.find(attribute => attribute?.name === colorAttributeName);
\t\t\tif (!attrInfo || !mapping.coloring_id_to_color) {{
\t\t\t\treturn;
\t\t\t}}

\t\t\tconst entries = Object.entries(mapping.coloring_id_to_color)
\t\t\t\t.map(([id, entry]) => [Number(id), entry])
\t\t\t\t.filter(([id, entry]) => Number.isFinite(id) && Array.isArray(entry?.rgb) && entry.rgb.length >= 3)
\t\t\t\t.sort((a, b) => a[0] - b[0]);
\t\t\tif (entries.length === 0) {{
\t\t\t\treturn;
\t\t\t}}

\t\t\tconst maxId = Math.max(...entries.map(([id]) => id));
\t\t\tattrInfo.range = [0, maxId];
\t\t\tattrInfo.initialRange = [0, maxId];

\t\t\tconst glslFloat = value => `${{Number(value).toFixed(8)}}`;
\t\t\tconst colorLines = entries.map(([id, entry]) => {{
\t\t\t\tconst rgb = entry.rgb.map(value => Math.max(0, Math.min(255, Number(value))) / 255);
\t\t\t\treturn `\\tif (abs(colorId - ${{glslFloat(id)}}) < 0.25) {{ return vec3(${{glslFloat(rgb[0])}}, ${{glslFloat(rgb[1])}}, ${{glslFloat(rgb[2])}}); }}`;
\t\t\t}});
\t\t\tconst shaderGetExtra = [
\t\t\t\t"vec3 getExtra(){{",
\t\t\t\t"\\t// THREEDTREES_COLORING_ID_SHADER: exact categorical sidecar mapping",
\t\t\t\t"\\tfloat colorId = floor(aExtra + 0.5);",
\t\t\t\t...colorLines,
\t\t\t\t"\\treturn vec3(0.15, 0.15, 0.15);",
\t\t\t\t"}}"
\t\t\t].join("\\n");

\t\t\tconst material = pointcloud.material;
\t\t\tconst installColoringShader = () => {{
\t\t\t\tlet source = material.vertexShader;
\t\t\t\tif (!source || source.includes("THREEDTREES_COLORING_ID_SHADER")) {{
\t\t\t\t\treturn;
\t\t\t\t}}
\t\t\t\tconst start = source.indexOf("vec3 getExtra(){{");
\t\t\t\tconst endMarker = "\\n\\nvec3 getColor(){{";
\t\t\t\tconst end = start >= 0 ? source.indexOf(endMarker, start) : -1;
\t\t\t\tif (start < 0 || end < 0) {{
\t\t\t\t\tconsole.warn("Could not install special coloring shader: getExtra() not found.");
\t\t\t\t\treturn;
\t\t\t\t}}
\t\t\t\tmaterial.vertexShader = source.slice(0, start) + shaderGetExtra + source.slice(end);
\t\t\t\tmaterial.needsUpdate = true;
\t\t\t}};

\t\t\tif (!material.__3dtreesOriginalUpdateShaderSource) {{
\t\t\t\tmaterial.__3dtreesOriginalUpdateShaderSource = material.updateShaderSource.bind(material);
\t\t\t\tmaterial.updateShaderSource = () => {{
\t\t\t\t\tmaterial.__3dtreesOriginalUpdateShaderSource();
\t\t\t\t\tinstallColoringShader();
\t\t\t\t}};
\t\t\t}}

\t\t\tmaterial.activeAttributeName = colorAttributeName;
\t\t\tif (typeof material.setRange === "function") {{
\t\t\t\tmaterial.setRange(colorAttributeName, [0, maxId]);
\t\t\t}}
\t\t\tmaterial.intensityRange = [0, maxId];
\t\t\tinstallColoringShader();

\t\t\tconst syncSidebar = () => {{
\t\t\t\tconst selector = window.$ ? $("#optMaterial") : null;
\t\t\t\tif (!selector || selector.length === 0) {{
\t\t\t\t\treturn;
\t\t\t\t}}
\t\t\t\tselector.val(colorAttributeName);
\t\t\t\ttry {{ selector.selectmenu("refresh"); }} catch (error) {{}}
\t\t\t}};
\t\t\tsyncSidebar();
\t\t\twindow.setTimeout(syncSidebar, 500);
\t\t\twindow.setTimeout(syncSidebar, 1500);

\t\t\tif (typeof viewer.render === "function") {{
\t\t\t\tviewer.render();
\t\t\t}}
\t\t}}
"""


def prepare_special_coloring_inputs(
    sources: Sequence[str],
    working_dir: Path,
    mapping_path: Path,
    *,
    instance_attribute: str = INSTANCE_ATTRIBUTE,
    palette_name: str = PALETTE_NAME,
    n_colors: int = N_COLORS,
    n_neighbors: int = N_NEIGHBORS,
    ground_instance_id: int = GROUND_INSTANCE_ID,
    ground_color: str = GROUND_COLOR_HEX,
    seed: int = RANDOM_SEED,
    chunk_size: int = CHUNK_SIZE,
    write_sidecar_json: bool = True,
) -> SpecialColoringResult:
    """Create temporary LAS/LAZ inputs with a coloring_id extra dimension."""
    palette_name = normalize_palette_name(palette_name)
    ground_color = normalize_hex_color(ground_color)
    validate_special_coloring_options(
        instance_attribute=instance_attribute,
        palette_name=palette_name,
        n_colors=n_colors,
        n_neighbors=n_neighbors,
        ground_color=ground_color,
    )
    source_files = discover_pointcloud_files(sources)
    if not source_files:
        raise ValueError("No LAS/LAZ files found for special coloring.")

    instance_stats = accumulate_instance_stats(
        source_files,
        instance_attribute=instance_attribute,
        ground_instance_id=ground_instance_id,
        chunk_size=chunk_size,
    )
    instance_to_coloring_id, coloring_id_to_color = assign_coloring_ids(
        instance_stats,
        n_colors=n_colors,
        n_neighbors=n_neighbors,
        palette_name=palette_name,
        seed=seed,
        ground_instance_id=ground_instance_id,
        ground_color=ground_color,
    )

    if write_sidecar_json:
        mapping_path.parent.mkdir(parents=True, exist_ok=True)
        write_mapping_json(
            mapping_path,
            instance_to_coloring_id,
            coloring_id_to_color,
            instance_attribute=instance_attribute,
            palette_name=palette_name,
            n_colors=n_colors,
            n_neighbors=n_neighbors,
            ground_instance_id=ground_instance_id,
            ground_color=ground_color,
        )

    colored_dir = working_dir / "special_coloring_inputs"
    colored_dir.mkdir(parents=True, exist_ok=True)
    for index, source_file in enumerate(source_files):
        target = colored_dir / f"{index:04d}_{regular_laz_name(source_file)}"
        write_colored_las(
            source_file,
            target,
            instance_to_coloring_id,
            instance_attribute=instance_attribute,
            ground_instance_id=ground_instance_id,
            chunk_size=chunk_size,
        )

    return SpecialColoringResult(
        sources=[str(colored_dir)],
        mapping_path=mapping_path,
        source_files=source_files,
        instance_count=sum(
            1
            for instance_id in instance_to_coloring_id
            if not is_ground_instance_id(instance_id, ground_instance_id)
        ),
    )


def discover_pointcloud_files(sources: Sequence[str]) -> List[Path]:
    files: List[Path] = []
    for source in sources:
        path = Path(source)
        if path.is_dir():
            files.extend(
                sorted(
                    child
                    for child in path.iterdir()
                    if child.is_file() and child.suffix.lower() in {".las", ".laz"}
                )
            )
        elif path.is_file() and path.suffix.lower() in {".las", ".laz"}:
            files.append(path)
    return files


def regular_laz_name(source_file: Path) -> str:
    """Return a temporary LAS/LAZ name that never asks laspy to write COPC."""
    name = source_file.name
    lower_name = name.lower()
    if lower_name.endswith(".copc.laz"):
        return f"{name[:-len('.copc.laz')]}.laz"
    return name


def accumulate_instance_stats(
    source_files: Sequence[Path],
    *,
    instance_attribute: str = INSTANCE_ATTRIBUTE,
    ground_instance_id: int = GROUND_INSTANCE_ID,
    chunk_size: int = CHUNK_SIZE,
) -> Dict[int, InstanceStats]:
    stats: Dict[int, InstanceStats] = {}
    for source_file in source_files:
        with laspy.open(str(source_file), **_open_kwargs(source_file)) as reader:
            _require_dimension(reader.header, instance_attribute, source_file)
            for chunk in reader.chunk_iterator(chunk_size):
                ids = _coerce_instance_ids(chunk[instance_attribute])
                if ids.size == 0:
                    continue
                ground_like = is_ground_instance_ids(ids, ground_instance_id)
                ground_ids, ground_counts = np.unique(ids[ground_like], return_counts=True)
                for instance_id, count in zip(ground_ids, ground_counts):
                    stats.setdefault(int(instance_id), InstanceStats()).count += int(count)

                non_ground = ~ground_like
                if not np.any(non_ground):
                    continue

                ids = ids[non_ground]
                xs = np.asarray(chunk.x, dtype=np.float64)[non_ground]
                ys = np.asarray(chunk.y, dtype=np.float64)[non_ground]
                zs = np.asarray(chunk.z, dtype=np.float64)[non_ground]

                unique_ids, inverse = np.unique(ids, return_inverse=True)
                counts = np.bincount(inverse)
                sum_x = np.bincount(inverse, weights=xs)
                sum_y = np.bincount(inverse, weights=ys)
                sum_z = np.bincount(inverse, weights=zs)

                for idx, instance_id in enumerate(unique_ids):
                    stat = stats.setdefault(int(instance_id), InstanceStats())
                    stat.count += int(counts[idx])
                    stat.sum_x += float(sum_x[idx])
                    stat.sum_y += float(sum_y[idx])
                    stat.sum_z += float(sum_z[idx])
    return stats


def assign_coloring_ids(
    instance_stats: Mapping[int, InstanceStats],
    *,
    n_colors: int = N_COLORS,
    n_neighbors: int = N_NEIGHBORS,
    palette_name: str = PALETTE_NAME,
    seed: int = RANDOM_SEED,
    ground_instance_id: int = GROUND_INSTANCE_ID,
    ground_color: str = GROUND_COLOR_HEX,
) -> Tuple[Dict[int, int], Dict[int, Dict[str, object]]]:
    if n_colors < 1:
        raise ValueError("n_colors must be at least 1.")
    if n_neighbors < 1:
        raise ValueError("n_neighbors must be at least 1.")
    palette_hex, palette_rgb, palette_lab = build_palette(palette_name, n_colors)
    coloring_id_to_color: Dict[int, Dict[str, object]] = {
        GROUND_COLORING_ID: {
            "hex": normalize_hex_color(ground_color),
            "rgb": [int(value) for value in np.rint(hex_to_rgb01(ground_color) * 255).astype(int)],
        }
    }
    for index, hex_color in enumerate(palette_hex, start=1):
        rgb = np.rint(palette_rgb[index - 1] * 255).astype(int)
        coloring_id_to_color[index] = {
            "hex": hex_color,
            "rgb": [int(rgb[0]), int(rgb[1]), int(rgb[2])],
        }

    valid_items = sorted(
        (instance_id, stat)
        for instance_id, stat in instance_stats.items()
        if not is_ground_instance_id(instance_id, ground_instance_id) and stat.count > 0
    )
    instance_to_coloring_id: Dict[int, int] = {
        int(instance_id): GROUND_COLORING_ID
        for instance_id, stat in instance_stats.items()
        if is_ground_instance_id(int(instance_id), ground_instance_id) and stat.count > 0
    }
    instance_to_coloring_id.setdefault(ground_instance_id, GROUND_COLORING_ID)
    if not valid_items:
        return instance_to_coloring_id, coloring_id_to_color

    instance_ids = np.array([instance_id for instance_id, _ in valid_items], dtype=np.int64)
    coords = np.array(
        [
            [stat.sum_x / stat.count, stat.sum_y / stat.count, stat.sum_z / stat.count]
            for _, stat in valid_items
        ],
        dtype=np.float64,
    )

    neighbor_query_count = min(n_neighbors + 1, len(instance_ids))
    indices, distances = nearest_neighbors(coords, neighbor_query_count)
    mean_distances = distances.mean(axis=1)
    sorted_order = np.lexsort((instance_ids, mean_distances))
    id_to_row = {int(instance_id): index for index, instance_id in enumerate(instance_ids)}
    color_distances = np.linalg.norm(
        palette_lab[:, None, :] - palette_lab[None, :, :],
        axis=2,
    )
    assigned = np.full(len(instance_ids), -1, dtype=np.int64)
    rng = np.random.default_rng(seed)

    for row in sorted_order:
        neighbor_colors = assigned[indices[row, 1 : n_neighbors + 1]]
        used = sorted(int(value) for value in np.unique(neighbor_colors) if value >= 0)
        if not used:
            new_color = int(rng.integers(0, n_colors))
        else:
            unused = [color for color in range(n_colors) if color not in used]
            if not unused:
                unused = list(range(n_colors))
            if len(unused) == 1:
                new_color = unused[0]
            else:
                dvals = color_distances[np.ix_(unused, used)].sum(axis=1)
                new_color = unused[int(np.argmax(dvals))]
        assigned[row] = new_color

    for instance_id in instance_ids:
        row = id_to_row[int(instance_id)]
        instance_to_coloring_id[int(instance_id)] = int(assigned[row]) + 1

    return instance_to_coloring_id, coloring_id_to_color


def nearest_neighbors(coords: np.ndarray, n_neighbors: int) -> Tuple[np.ndarray, np.ndarray]:
    try:
        from sklearn.neighbors import NearestNeighbors

        nbrs = NearestNeighbors(n_neighbors=n_neighbors).fit(coords)
        distances, indices = nbrs.kneighbors(coords)
        return indices, distances
    except Exception:
        distances = np.linalg.norm(coords[:, None, :] - coords[None, :, :], axis=2)
        indices = np.argsort(distances, axis=1)[:, :n_neighbors]
        sorted_distances = np.take_along_axis(distances, indices, axis=1)
        return indices, sorted_distances


def write_colored_las(
    source_file: Path,
    target_file: Path,
    instance_to_coloring_id: Mapping[int, int],
    *,
    instance_attribute: str = INSTANCE_ATTRIBUTE,
    ground_instance_id: int = GROUND_INSTANCE_ID,
    chunk_size: int = CHUNK_SIZE,
) -> None:
    target_file.parent.mkdir(parents=True, exist_ok=True)
    with laspy.open(str(source_file), **_open_kwargs(source_file)) as reader:
        _require_dimension(reader.header, instance_attribute, source_file)
        _reject_existing_dimension(reader.header, COLOR_ATTRIBUTE, source_file)

        source_dimensions = list(reader.header.point_format.dimension_names)
        output_header = build_colored_header(reader.header, instance_attribute=instance_attribute)
        output_header.add_extra_dim(
            laspy.ExtraBytesParams(
                name=COLOR_ATTRIBUTE,
                type=COLOR_ATTRIBUTE_DTYPE,
                description="Julian special coloring id",
            )
        )

        mapping_keys = np.array(sorted(instance_to_coloring_id.keys()), dtype=np.int64)
        mapping_values = np.array(
            [instance_to_coloring_id[int(key)] for key in mapping_keys],
            dtype=COLOR_ATTRIBUTE_DTYPE,
        )

        with laspy.open(
            str(target_file),
            mode="w",
            header=output_header,
            do_compress=target_file.suffix.lower() == ".laz",
            **_open_kwargs(target_file),
        ) as writer:
            for chunk in reader.chunk_iterator(chunk_size):
                out_record = laspy.ScaleAwarePointRecord.zeros(len(chunk), header=output_header)
                for dim_name in source_dimensions:
                    if dim_name == instance_attribute:
                        out_record[dim_name] = _coerce_instance_ids(chunk[dim_name]).astype(np.int32)
                    else:
                        out_record[dim_name] = chunk[dim_name]
                out_record[COLOR_ATTRIBUTE] = map_instances_to_coloring_ids(
                    chunk[instance_attribute],
                    mapping_keys,
                    mapping_values,
                    instance_attribute=instance_attribute,
                    ground_instance_id=ground_instance_id,
                )
                writer.write_points(out_record)


def build_colored_header(
    source_header: laspy.LasHeader,
    *,
    instance_attribute: str = INSTANCE_ATTRIBUTE,
) -> laspy.LasHeader:
    output_header = laspy.LasHeader(
        point_format=source_header.point_format.id,
        version=source_header.version,
    )
    output_header.offsets = source_header.offsets
    output_header.scales = source_header.scales

    for vlr in source_header.vlrs:
        user_id = getattr(vlr, "user_id", "")
        record_id = getattr(vlr, "record_id", None)
        if str(user_id).lower() == "copc":
            continue
        if record_id == 4 and user_id == "LASF_Spec":
            continue
        output_header.vlrs.append(vlr)

    extra_params = []
    for dim in source_header.point_format.extra_dimensions:
        dim_type = np.int32 if dim.name == instance_attribute else dim.dtype
        extra_params.append(
            laspy.ExtraBytesParams(
                name=dim.name,
                type=dim_type,
                description=getattr(dim, "description", "") or "",
                offsets=getattr(dim, "offsets", None),
                scales=getattr(dim, "scales", None),
                no_data=getattr(dim, "no_data", None),
            )
        )
    if extra_params:
        output_header.add_extra_dims(extra_params)

    return output_header


def map_instances_to_coloring_ids(
    raw_instance_ids: object,
    mapping_keys: np.ndarray,
    mapping_values: np.ndarray,
    *,
    instance_attribute: str = INSTANCE_ATTRIBUTE,
    ground_instance_id: int = GROUND_INSTANCE_ID,
) -> np.ndarray:
    ids = _coerce_instance_ids(raw_instance_ids)
    coloring_ids = np.zeros(ids.shape[0], dtype=COLOR_ATTRIBUTE_DTYPE)
    if mapping_keys.size == 0 or ids.size == 0:
        return coloring_ids

    positions = np.searchsorted(mapping_keys, ids)
    in_range = positions < mapping_keys.size
    matches = np.zeros(ids.shape[0], dtype=bool)
    matches[in_range] = mapping_keys[positions[in_range]] == ids[in_range]
    coloring_ids[matches] = mapping_values[positions[matches]]

    unmatched = (~matches) & (~is_ground_instance_ids(ids, ground_instance_id))
    if np.any(unmatched):
        missing = np.unique(ids[unmatched])[:10]
        raise ValueError(f"Missing coloring_id assignments for {instance_attribute} values: {missing.tolist()}")

    return coloring_ids


def is_ground_instance_id(instance_id: int, ground_instance_id: int = GROUND_INSTANCE_ID) -> bool:
    return instance_id == ground_instance_id or instance_id < 0


def is_ground_instance_ids(ids: np.ndarray, ground_instance_id: int = GROUND_INSTANCE_ID) -> np.ndarray:
    return (ids == ground_instance_id) | (ids < 0)


def write_mapping_json(
    mapping_path: Path,
    instance_to_coloring_id: Mapping[int, int],
    coloring_id_to_color: Mapping[int, Mapping[str, object]],
    *,
    instance_attribute: str = INSTANCE_ATTRIBUTE,
    palette_name: str = PALETTE_NAME,
    n_colors: int = N_COLORS,
    n_neighbors: int = N_NEIGHBORS,
    ground_instance_id: int = GROUND_INSTANCE_ID,
    ground_color: str = GROUND_COLOR_HEX,
) -> None:
    payload = {
        "version": 1,
        "instance_attribute": instance_attribute,
        "color_attribute": COLOR_ATTRIBUTE,
        "ground_instance_id": ground_instance_id,
        "ground_coloring_id": GROUND_COLORING_ID,
        "ground_color": normalize_hex_color(ground_color),
        "palette": palette_name,
        "n_colors": n_colors,
        "n_neighbors": n_neighbors,
        "coloring_id_to_color": {
            str(coloring_id): value
            for coloring_id, value in sorted(coloring_id_to_color.items())
        },
        "instance_id_to_coloring_id": {
            str(instance_id): int(coloring_id)
            for instance_id, coloring_id in sorted(instance_to_coloring_id.items())
        },
    }
    mapping_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def build_palette(
    palette_name: str,
    n_colors: int,
) -> Tuple[List[str], np.ndarray, np.ndarray]:
    base_palette = resolve_palette(palette_name)
    base_rgb = np.array([hex_to_rgb01(color) for color in base_palette], dtype=np.float64)
    base_lab = xyz_to_lab(srgb_to_xyz(base_rgb))
    if n_colors <= len(base_palette):
        rgb = base_rgb[:n_colors]
        lab = base_lab[:n_colors]
    else:
        base_positions = np.linspace(0.0, 1.0, len(base_palette))
        target_positions = np.linspace(0.0, 1.0, n_colors)
        lab = np.column_stack(
            [
                np.interp(target_positions, base_positions, base_lab[:, channel])
                for channel in range(3)
            ]
        )
        rgb = np.clip(xyz_to_srgb(lab_to_xyz(lab)), 0.0, 1.0)
    return [rgb01_to_hex(color) for color in rgb], rgb, lab


def validate_special_coloring_options(
    *,
    instance_attribute: str,
    palette_name: str,
    n_colors: int,
    n_neighbors: int,
    ground_color: str,
) -> None:
    if not instance_attribute.strip():
        raise ValueError("special coloring instance attribute must not be empty.")
    if n_colors < 1:
        raise ValueError("special coloring n_colors must be at least 1.")
    if n_neighbors < 1:
        raise ValueError("special coloring n_neighbors must be at least 1.")
    resolve_palette(palette_name)
    normalize_hex_color(ground_color)


def resolve_palette(palette_name: str) -> List[str]:
    key = palette_name.strip().lower()
    if key in PALETTES:
        return PALETTES[key]
    colors = [part.strip() for part in palette_name.split(",") if part.strip()]
    if colors:
        return [normalize_hex_color(color) for color in colors]
    raise ValueError(
        f"Unknown special coloring palette {palette_name!r}. "
        f"Expected one of {sorted(PALETTES)} or a comma-separated #RRGGBB list."
    )


def normalize_palette_name(value: str) -> str:
    key = value.strip().lower()
    if key in PALETTES:
        return key
    colors = [part.strip() for part in value.split(",") if part.strip()]
    if not colors:
        raise ValueError(
            f"Unknown special coloring palette {value!r}. "
            f"Expected one of {sorted(PALETTES)} or a comma-separated #RRGGBB list."
        )
    return ",".join(normalize_hex_color(color) for color in colors)


def normalize_hex_color(value: str) -> str:
    raw = value.strip().replace("__pd__", "#")
    if not raw.startswith("#"):
        raw = f"#{raw}"
    hex_part = raw[1:]
    if len(hex_part) != 6:
        raise ValueError(f"Expected #RRGGBB color, got {value!r}")
    try:
        int(hex_part, 16)
    except ValueError as exc:
        raise ValueError(f"Expected #RRGGBB color, got {value!r}") from exc
    return f"#{hex_part.lower()}"


def hex_to_rgb01(value: str) -> np.ndarray:
    raw = normalize_hex_color(value).lstrip("#")
    return np.array(
        [int(raw[0:2], 16), int(raw[2:4], 16), int(raw[4:6], 16)],
        dtype=np.float64,
    ) / 255.0


def rgb01_to_hex(rgb: Iterable[float]) -> str:
    values = np.rint(np.clip(np.array(list(rgb), dtype=np.float64), 0.0, 1.0) * 255).astype(int)
    return f"#{values[0]:02x}{values[1]:02x}{values[2]:02x}"


def srgb_to_xyz(rgb: np.ndarray) -> np.ndarray:
    linear = np.where(rgb <= 0.04045, rgb / 12.92, ((rgb + 0.055) / 1.055) ** 2.4)
    return linear @ SRGB_TO_XYZ.T


def xyz_to_srgb(xyz: np.ndarray) -> np.ndarray:
    linear = xyz @ XYZ_TO_SRGB.T
    linear = np.clip(linear, 0.0, None)
    return np.where(linear <= 0.0031308, 12.92 * linear, 1.055 * (linear ** (1 / 2.4)) - 0.055)


def xyz_to_lab(xyz: np.ndarray) -> np.ndarray:
    scaled = xyz / D65_WHITE
    delta = 6 / 29
    transformed = np.where(
        scaled > delta**3,
        np.cbrt(scaled),
        scaled / (3 * delta**2) + 4 / 29,
    )
    return np.column_stack(
        [
            116 * transformed[:, 1] - 16,
            500 * (transformed[:, 0] - transformed[:, 1]),
            200 * (transformed[:, 1] - transformed[:, 2]),
        ]
    )


def lab_to_xyz(lab: np.ndarray) -> np.ndarray:
    fy = (lab[:, 0] + 16) / 116
    fx = fy + lab[:, 1] / 500
    fz = fy - lab[:, 2] / 200
    f = np.column_stack([fx, fy, fz])
    delta = 6 / 29
    scaled = np.where(
        f > delta,
        f**3,
        3 * delta**2 * (f - 4 / 29),
    )
    return scaled * D65_WHITE


def _coerce_instance_ids(raw_ids: object) -> np.ndarray:
    ids = np.asarray(raw_ids)
    if ids.ndim > 1:
        ids = ids[:, 0]
    if ids.size == 0:
        return np.empty(0, dtype=np.int64)
    if np.issubdtype(ids.dtype, np.floating):
        finite = np.isfinite(ids)
        if not np.all(finite):
            raise ValueError("PredInstance contains non-finite values.")
        rounded = np.rint(ids)
        if not np.allclose(ids, rounded):
            raise ValueError("PredInstance contains non-integer values.")
        ids = rounded
    return ids.astype(np.int64, copy=False)


def _open_kwargs(path: Path) -> Dict[str, object]:
    if path.suffix.lower() != ".laz":
        return {}
    backend = _laz_backend()
    return {"laz_backend": backend} if backend is not None else {}


def _laz_backend() -> object:
    if hasattr(laspy.LazBackend, "LazrsParallel"):
        return laspy.LazBackend.LazrsParallel
    if hasattr(laspy.LazBackend, "Lazrs"):
        return laspy.LazBackend.Lazrs
    return None


def _require_dimension(header: laspy.LasHeader, name: str, source_file: Path) -> None:
    if name not in set(header.point_format.dimension_names):
        raise ValueError(f"{source_file} does not contain required dimension {name!r}.")


def _reject_existing_dimension(header: laspy.LasHeader, name: str, source_file: Path) -> None:
    if name in set(header.point_format.dimension_names):
        raise ValueError(f"{source_file} already contains dimension {name!r}.")
