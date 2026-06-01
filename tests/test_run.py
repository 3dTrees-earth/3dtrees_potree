from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

try:
    from parameters import Parameters  # noqa: E402
    from run import (  # noqa: E402
        build_potree_command,
        copy_mapping_to_metadata_siblings,
        expand_boolean_flags,
        patch_special_coloring_viewer_html,
    )
except ModuleNotFoundError as exc:
    if exc.name != "pydantic_settings":
        raise
    raise unittest.SkipTest("pydantic-settings is not installed in this Python environment")


class RunCommandTests(unittest.TestCase):
    def test_empty_attribute_override_passes_no_attributes(self) -> None:
        params = Parameters(
            _cli_parse_args=[],
            source=["/input/source.laz"],
            outdir=Path("/output"),
            attributes=["rgb,PredInstance,coloring_id"],
        )

        cmd = build_potree_command(
            params,
            sources=["/tmp/special_coloring_inputs"],
            attributes=[],
        )

        self.assertNotIn("--attributes", cmd)

    def test_mapping_is_copied_beside_generated_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            outdir = Path(tmp) / "output"
            metadata_dir = outdir / "pointclouds" / "viewer"
            metadata_dir.mkdir(parents=True)
            (metadata_dir / "metadata.json").write_text("{}", encoding="utf-8")
            mapping_path = outdir / "special_coloring_mapping.json"
            mapping_path.parent.mkdir(parents=True, exist_ok=True)
            mapping_path.write_text('{"version": 1}\n', encoding="utf-8")

            copied_paths = copy_mapping_to_metadata_siblings(outdir, mapping_path)

            self.assertEqual(copied_paths, [metadata_dir / "special_coloring_mapping.json"])
            self.assertEqual(
                (metadata_dir / "special_coloring_mapping.json").read_text(encoding="utf-8"),
                mapping_path.read_text(encoding="utf-8"),
            )

    def test_sidecar_boolean_flag_expands_for_cli_parser(self) -> None:
        self.assertEqual(
            expand_boolean_flags(["--special-coloring-sidecar-json"]),
            ["--special-coloring-sidecar-json=true"],
        )

    def test_generated_viewer_is_patched_for_special_coloring_sidecar(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            outdir = Path(tmp)
            html_path = outdir / "viewer.html"
            html_path.write_text(
                """
<script>
Potree.loadPointCloud("./pointclouds/viewer/metadata.json", "viewer", e => {
    let pointcloud = e.pointcloud;
    let material = pointcloud.material;
    material.activeAttributeName = "rgba";
    viewer.fitToScreen();
});
</script>
""",
                encoding="utf-8",
            )

            patched_path = patch_special_coloring_viewer_html(
                outdir,
                "viewer",
                "special_coloring_mapping.json",
            )

            patched = html_path.read_text(encoding="utf-8")
            self.assertEqual(patched_path, html_path)
            self.assertIn("3DTREES_SPECIAL_COLORING_VIEWER_PATCH", patched)
            self.assertIn("THREEDTREES_COLORING_ID_SHADER", patched)
            self.assertIn("special_coloring_mapping.json", patched)
            self.assertIn('material.setRange(colorAttributeName, [0, maxId]);', patched)
            self.assertIn("material.activeAttributeName = colorAttributeName;", patched)
            self.assertIn('selector.val(colorAttributeName);', patched)
            self.assertNotIn("material.gradient = gradient;", patched)
            self.assertIn('apply3DtreesSpecialColoring(pointcloud, "./pointclouds/viewer/metadata.json");', patched)


if __name__ == "__main__":
    unittest.main()
