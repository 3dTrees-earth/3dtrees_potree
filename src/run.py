#!/usr/bin/env python3

import sys
import logging
import subprocess
import tempfile
import shutil
from pathlib import Path
from typing import Iterable, List, Optional, Sequence

from parameters import Parameters
from special_coloring import prepare_special_coloring_inputs

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

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
    """Let Galaxy-style bare boolean flags work with pydantic-settings CLI parsing."""
    expanded: List[str] = []
    for token in argv:
        if token in BOOLEAN_FLAGS:
            expanded.append(f"{token}=true")
        else:
            expanded.append(token)
    return expanded


def normalize_attributes(attributes: Optional[Iterable[str]]) -> List[str]:
    """Normalize CLI attributes; Galaxy passes comma-separated text."""
    normalized: List[str] = []
    seen = set()
    for value in attributes or []:
        for raw_part in str(value).split(","):
            attr = raw_part.strip()
            key = attr.lower()
            if not attr or key in seen:
                continue
            seen.add(key)
            normalized.append(attr)
    return normalized


def build_potree_command(
    params: Parameters,
    *,
    sources: Optional[Sequence[str]] = None,
    attributes: Optional[Sequence[str]] = None,
) -> List[str]:
    """Build PotreeConverter command from parameters"""
    # Use absolute path to help PotreeConverter find its resources
    cmd = ["/opt/PotreeConverter/PotreeConverter"]
    
    # Add source files/directories
    for source in sources or params.source:
        cmd.append(source)
    
    # Add output directory if specified
    if params.outdir:
        cmd.extend(["-o", str(params.outdir)])
    
    # Add encoding
    if params.encoding != "DEFAULT":
        cmd.extend(["--encoding", params.encoding])
    
    # Add sampling method
    if params.method != "poisson":
        cmd.extend(["-m", params.method])
    
    # Add chunk method
    if params.chunk_method != "LASZIP":
        cmd.extend(["--chunkMethod", params.chunk_method])
    
    # Add attributes
    for attr in normalize_attributes(attributes if attributes is not None else params.attributes):
        cmd.extend(["--attributes", attr])
    
    # Add boolean flags
    if params.keep_chunks:
        cmd.append("--keep-chunks")
    
    if params.no_chunking:
        cmd.append("--no-chunking")
    
    if params.no_indexing:
        cmd.append("--no-indexing")
    
    # Add page generation
    if params.generate_page:
        cmd.extend(["-p", params.generate_page])
    
    if params.title:
        cmd.extend(["--title", params.title])
    
    return cmd


def execute_potree_command(cmd: Sequence[str]) -> str:
    result = subprocess.run(
        list(cmd),
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True
    )
    return result.stdout


def copy_mapping_to_metadata_siblings(outdir: Path, mapping_path: Path) -> List[Path]:
    """Place the mapping beside metadata.json files for frontend discovery."""
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
    helper = f"""

		const THREEDTREES_SPECIAL_COLORING_VIEWER_PATCH = true; // {marker}
		async function apply3DtreesSpecialColoring(pointcloud, metadataUrl) {{
			const mappingUrl = new URL("{mapping_filename}", new URL(metadataUrl, window.location.href)).href;
			let mapping;
			try {{
				const response = await fetch(mappingUrl);
				if (!response.ok) {{
					console.warn(`Special coloring mapping unavailable (${{response.status}}).`);
					return;
				}}
				mapping = await response.json();
			}} catch (error) {{
				console.warn("Special coloring mapping could not be loaded.", error);
				return;
			}}

			const colorAttributeName = mapping.color_attribute || "coloring_id";
			const attributes = pointcloud?.pcoGeometry?.pointAttributes?.attributes || [];
			const attrInfo = attributes.find(attribute => attribute?.name === colorAttributeName);
			if (!attrInfo || !mapping.coloring_id_to_color) {{
				return;
			}}

			const entries = Object.entries(mapping.coloring_id_to_color)
				.map(([id, entry]) => [Number(id), entry])
				.filter(([id, entry]) => Number.isFinite(id) && Array.isArray(entry?.rgb) && entry.rgb.length >= 3)
				.sort((a, b) => a[0] - b[0]);
			if (entries.length === 0) {{
				return;
			}}

			const maxId = Math.max(...entries.map(([id]) => id));
			attrInfo.range = [0, maxId];
			attrInfo.initialRange = [0, maxId];

			const glslFloat = value => `${{Number(value).toFixed(8)}}`;
			const colorLines = entries.map(([id, entry]) => {{
				const rgb = entry.rgb.map(value => Math.max(0, Math.min(255, Number(value))) / 255);
				return `\\tif (abs(colorId - ${{glslFloat(id)}}) < 0.25) {{ return vec3(${{glslFloat(rgb[0])}}, ${{glslFloat(rgb[1])}}, ${{glslFloat(rgb[2])}}); }}`;
			}});
			const shaderGetExtra = [
				"vec3 getExtra(){{",
				"\\t// THREEDTREES_COLORING_ID_SHADER: exact categorical sidecar mapping",
				"\\tfloat colorId = floor(aExtra + 0.5);",
				...colorLines,
				"\\treturn vec3(0.15, 0.15, 0.15);",
				"}}"
			].join("\\n");

			const material = pointcloud.material;
			const installColoringShader = () => {{
				let source = material.vertexShader;
				if (!source || source.includes("THREEDTREES_COLORING_ID_SHADER")) {{
					return;
				}}
				const start = source.indexOf("vec3 getExtra(){{");
				const endMarker = "\\n\\nvec3 getColor(){{";
				const end = start >= 0 ? source.indexOf(endMarker, start) : -1;
				if (start < 0 || end < 0) {{
					console.warn("Could not install special coloring shader: getExtra() not found.");
					return;
				}}
				material.vertexShader = source.slice(0, start) + shaderGetExtra + source.slice(end);
				material.needsUpdate = true;
			}};

			if (!material.__3dtreesOriginalUpdateShaderSource) {{
				material.__3dtreesOriginalUpdateShaderSource = material.updateShaderSource.bind(material);
				material.updateShaderSource = () => {{
					material.__3dtreesOriginalUpdateShaderSource();
					installColoringShader();
				}};
			}}

			material.activeAttributeName = colorAttributeName;
			if (typeof material.setRange === "function") {{
				material.setRange(colorAttributeName, [0, maxId]);
			}}
			material.intensityRange = [0, maxId];
			installColoringShader();

			const syncSidebar = () => {{
				const selector = window.$ ? $("#optMaterial") : null;
				if (!selector || selector.length === 0) {{
					return;
				}}
				selector.val(colorAttributeName);
				try {{ selector.selectmenu("refresh"); }} catch (error) {{}}
			}};
			syncSidebar();
			window.setTimeout(syncSidebar, 500);
			window.setTimeout(syncSidebar, 1500);

			if (typeof viewer.render === "function") {{
				viewer.render();
			}}
		}}
"""
    load_line = f'Potree.loadPointCloud("{metadata_url}", "{page_name}", e => {{'
    if load_line not in html:
        logger.warning("Could not patch %s: expected Potree.loadPointCloud line not found", html_path)
        return None

    patched = html.replace(load_line, helper + "\n\n\t\t" + load_line, 1)
    active_attr_line = 'material.activeAttributeName = "rgba";'
    if active_attr_line not in patched:
        logger.warning("Could not patch %s: expected activeAttributeName line not found", html_path)
        return None
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


def execute_special_coloring_conversion(params: Parameters) -> str:
    if params.outdir is None:
        params.outdir = Path("output")

    params.outdir.parent.mkdir(parents=True, exist_ok=True)
    if params.attributes:
        logger.info("Ignoring --attributes because --special-coloring uses PotreeConverter defaults.")

    with tempfile.TemporaryDirectory(
        prefix="potree_special_coloring_",
        dir=str(params.outdir.parent),
    ) as tmp_dir:
        mapping_path = params.outdir / "special_coloring_mapping.json"
        result = prepare_special_coloring_inputs(
            params.source,
            Path(tmp_dir),
            mapping_path,
            instance_attribute=params.special_coloring_instance_attribute,
            palette_name=params.special_coloring_palette,
            n_colors=params.special_coloring_n_colors,
            n_neighbors=params.special_coloring_n_neighbors,
            ground_instance_id=params.special_coloring_ground_id,
            ground_color=params.special_coloring_ground_color,
            write_sidecar_json=params.special_coloring_sidecar_json,
        )
        logger.info(
            "Special coloring prepared %s input file(s), %s non-ground instance(s), "
            "instance_attribute=%s, palette=%s, n_colors=%s, n_neighbors=%s, ground_id=%s, sidecar_json=%s, mapping=%s",
            len(result.source_files),
            result.instance_count,
            params.special_coloring_instance_attribute,
            params.special_coloring_palette,
            params.special_coloring_n_colors,
            params.special_coloring_n_neighbors,
            params.special_coloring_ground_id,
            params.special_coloring_sidecar_json,
            result.mapping_path if params.special_coloring_sidecar_json else None,
        )
        cmd = build_potree_command(params, sources=result.sources, attributes=[])
        logger.info(f"Executing: {' '.join(cmd)}")
        stdout = execute_potree_command(cmd)
        if params.special_coloring_sidecar_json:
            copied_paths = copy_mapping_to_metadata_siblings(params.outdir, mapping_path)
            for copied_path in copied_paths:
                logger.info("Copied special coloring mapping beside metadata: %s", copied_path)
            if params.generate_page:
                patched_html = patch_special_coloring_viewer_html(
                    params.outdir,
                    params.generate_page,
                    mapping_path.name,
                )
                if patched_html:
                    logger.info("Patched generated viewer for special coloring sidecar: %s", patched_html)
        return stdout


def main():
    """Main execution function"""
    try:
        sys.argv = [sys.argv[0], *expand_boolean_flags(sys.argv[1:])]
        params = Parameters()
        logger.info(f"Parameters: {params}")

        if params.grid_size:
            logger.info("Ignoring --grid-size: PotreeConverter 2.1.1 selects grid size automatically.")
        if params.numthreads:
            logger.info("Ignoring --numthreads: PotreeConverter 2.1.1 uses its built-in thread selection.")

        if params.special_coloring:
            stdout = execute_special_coloring_conversion(params)
        else:
            cmd = build_potree_command(params)
            logger.info(f"Executing: {' '.join(cmd)}")
            stdout = execute_potree_command(cmd)
        print(stdout)

        logger.info("PotreeConverter completed successfully")
        return 0

    except subprocess.CalledProcessError as e:
        logger.error(f"PotreeConverter failed with exit code {e.returncode}")
        logger.error(f"Output: {e.stdout}")
        return e.returncode

    except Exception as e:
        logger.error(f"Error: {e}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
