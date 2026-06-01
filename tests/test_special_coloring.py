from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

import laspy
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from special_coloring import (  # noqa: E402
    COLOR_ATTRIBUTE,
    INSTANCE_ATTRIBUTE,
    InstanceStats,
    assign_coloring_ids,
    build_colored_header,
    normalize_hex_color,
    prepare_special_coloring_inputs,
    regular_laz_name,
    resolve_palette,
)


def make_segmented_las(path: Path) -> None:
    header = laspy.LasHeader(point_format=7, version="1.4")
    header.offsets = np.array([0.0, 0.0, 0.0])
    header.scales = np.array([0.001, 0.001, 0.001])
    header.add_extra_dim(laspy.ExtraBytesParams(name=INSTANCE_ATTRIBUTE, type=np.int32))
    las = laspy.LasData(header)
    coords = np.array(
        [
            [-1.0, 0.0, 0.0],
            [-1.1, 0.0, 0.1],
            [0.0, 0.0, 0.0],
            [0.1, 0.0, 0.1],
            [0.0, 0.1, 0.2],
            [1.0, 0.0, 0.0],
            [1.1, 0.0, 0.1],
            [1.0, 0.1, 0.2],
            [3.0, 0.0, 0.0],
            [3.1, 0.0, 0.1],
            [3.0, 0.1, 0.2],
        ],
        dtype=float,
    )
    las.x = coords[:, 0]
    las.y = coords[:, 1]
    las.z = coords[:, 2]
    las.red = np.array([90, 95, 100, 110, 120, 200, 210, 220, 300, 310, 320], dtype=np.uint16)
    las.green = las.red + 1
    las.blue = las.red + 2
    las.PredInstance = np.array([-1, -1, 0, 0, 0, 1, 1, 1, 2, 2, 2], dtype=np.int32)
    if path.suffix.lower() == ".laz":
        las.write(path, do_compress=True, laz_backend=laspy.LazBackend.LazrsParallel)
    else:
        las.write(path)


class SpecialColoringTests(unittest.TestCase):
    def test_assign_coloring_ids_is_deterministic_and_neighbor_aware(self) -> None:
        stats = {
            1: InstanceStats(count=3, sum_x=0.0, sum_y=0.0, sum_z=0.0),
            2: InstanceStats(count=3, sum_x=3.0, sum_y=0.0, sum_z=0.0),
            3: InstanceStats(count=3, sum_x=30.0, sum_y=0.0, sum_z=0.0),
        }

        first_mapping, first_colors = assign_coloring_ids(stats)
        second_mapping, second_colors = assign_coloring_ids(stats)

        self.assertEqual(first_mapping, second_mapping)
        self.assertEqual(first_colors, second_colors)
        self.assertEqual(first_mapping[0], 0)
        self.assertIn(first_mapping[1], range(1, 11))
        self.assertIn(first_mapping[2], range(1, 11))
        self.assertNotEqual(first_mapping[1], first_mapping[2])

    def test_n_neighbors_counts_real_neighbors_not_self(self) -> None:
        stats = {
            1: InstanceStats(count=1, sum_x=0.0, sum_y=0.0, sum_z=0.0),
            2: InstanceStats(count=1, sum_x=1.0, sum_y=0.0, sum_z=0.0),
        }

        mapping, _ = assign_coloring_ids(stats, n_colors=2, n_neighbors=1)

        self.assertNotEqual(mapping[1], mapping[2])

    def test_prepare_special_coloring_preserves_rgb_and_adds_mapping(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            source = tmp_path / "input.laz"
            make_segmented_las(source)

            result = prepare_special_coloring_inputs(
                [str(source)],
                tmp_path / "work",
                tmp_path / "output" / "special_coloring_mapping.json",
                chunk_size=4,
            )

            self.assertEqual(result.instance_count, 2)
            mapping = json.loads(result.mapping_path.read_text(encoding="utf-8"))
            self.assertEqual(mapping["color_attribute"], COLOR_ATTRIBUTE)
            self.assertEqual(mapping["instance_attribute"], INSTANCE_ATTRIBUTE)
            self.assertEqual(mapping["palette"], "candy")
            self.assertEqual(mapping["instance_id_to_coloring_id"]["0"], 0)
            self.assertEqual(mapping["instance_id_to_coloring_id"]["-1"], 0)
            self.assertEqual(mapping["coloring_id_to_color"]["0"]["rgb"], [128, 128, 128])
            self.assertIn(mapping["instance_id_to_coloring_id"]["1"], range(1, 11))

            colored_file = next(Path(result.sources[0]).glob("*.laz"))
            colored = laspy.read(colored_file)
            original = laspy.read(source)

            self.assertIn(COLOR_ATTRIBUTE, list(colored.point_format.dimension_names))
            np.testing.assert_array_equal(colored.red, original.red)
            np.testing.assert_array_equal(colored.green, original.green)
            np.testing.assert_array_equal(colored.blue, original.blue)
            np.testing.assert_array_equal(colored.PredInstance, original.PredInstance)
            self.assertTrue(np.all(colored.coloring_id[:5] == 0))
            self.assertTrue(np.all(colored.coloring_id[5:] >= 1))

    def test_prepare_special_coloring_uses_requested_palette_params(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            source = tmp_path / "input.laz"
            make_segmented_las(source)

            result = prepare_special_coloring_inputs(
                [str(source)],
                tmp_path / "work",
                tmp_path / "output" / "special_coloring_mapping.json",
                palette_name="pastel",
                n_colors=4,
                n_neighbors=3,
                ground_color="#112233",
                chunk_size=4,
            )

            mapping = json.loads(result.mapping_path.read_text(encoding="utf-8"))
            self.assertEqual(mapping["palette"], "pastel")
            self.assertEqual(mapping["n_colors"], 4)
            self.assertEqual(mapping["n_neighbors"], 3)
            self.assertEqual(mapping["ground_color"], "#112233")
            self.assertEqual(mapping["coloring_id_to_color"]["0"]["rgb"], [17, 34, 51])
            self.assertEqual(len(mapping["coloring_id_to_color"]), 5)

    def test_prepare_special_coloring_can_skip_sidecar_json(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            source = tmp_path / "input.laz"
            mapping_path = tmp_path / "output" / "special_coloring_mapping.json"
            make_segmented_las(source)

            result = prepare_special_coloring_inputs(
                [str(source)],
                tmp_path / "work",
                mapping_path,
                write_sidecar_json=False,
                chunk_size=4,
            )

            self.assertEqual(result.mapping_path, mapping_path)
            self.assertFalse(mapping_path.exists())

    def test_resolve_palette_accepts_custom_hex_list(self) -> None:
        self.assertEqual(resolve_palette("#ABCDEF,123456"), ["#abcdef", "#123456"])

    def test_galaxy_hash_placeholder_is_normalized_for_colors(self) -> None:
        self.assertEqual(normalize_hex_color("__pd__ABCDEF"), "#abcdef")

    def test_copc_source_gets_regular_laz_temporary_name(self) -> None:
        self.assertEqual(regular_laz_name(Path("tile.copc.laz")), "tile.laz")
        self.assertEqual(regular_laz_name(Path("tile.laz")), "tile.laz")

    def test_colored_header_drops_copc_vlrs(self) -> None:
        header = laspy.LasHeader(point_format=7, version="1.4")
        header.vlrs.append(laspy.VLR(user_id="copc", record_id=1, description="", record_data=b""))

        output_header = build_colored_header(header)

        self.assertNotIn("copc", {vlr.user_id.lower() for vlr in output_header.vlrs})


if __name__ == "__main__":
    unittest.main()
