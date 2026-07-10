from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

import laspy
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from special_coloring import build_color_attribute_names, run_special_coloring_conversion


def write_segmented_las(path: Path) -> None:
    header = laspy.LasHeader(point_format=3, version="1.2")
    header.add_extra_dim(laspy.ExtraBytesParams(name="PredInstance_SAT", type=np.uint16))
    header.add_extra_dim(laspy.ExtraBytesParams(name="PredInstance_FM", type=np.uint16))
    header.add_extra_dim(laspy.ExtraBytesParams(name="species_id_FM", type=np.uint8))
    header.add_extra_dim(laspy.ExtraBytesParams(name="species_prob_FM", type=np.float32))
    header.add_extra_dim(laspy.ExtraBytesParams(name="PredSemantic_FM", type=np.uint16))
    header.add_extra_dim(laspy.ExtraBytesParams(name="PredScore_FM", type=np.float32))

    point_count = 4
    las = laspy.LasData(header)
    values = np.arange(point_count, dtype=np.float64)
    las.x = values
    las.y = values + 10
    las.z = values + 20
    las.intensity = np.array([10, 20, 30, 40], dtype=np.uint16)
    las.return_number = np.ones(point_count, dtype=np.uint8)
    las.number_of_returns = np.ones(point_count, dtype=np.uint8)
    las.classification = np.array([1, 2, 3, 4], dtype=np.uint8)
    las.scan_angle_rank = np.array([-2, -1, 0, 1], dtype=np.int8)
    las.user_data = np.array([0, 1, 2, 3], dtype=np.uint8)
    las.point_source_id = np.array([100, 100, 101, 101], dtype=np.uint16)
    las.gps_time = np.array([0.1, 0.2, 0.3, 0.4], dtype=np.float64)
    las.red = np.array([100, 200, 300, 400], dtype=np.uint16)
    las.green = np.array([110, 210, 310, 410], dtype=np.uint16)
    las.blue = np.array([120, 220, 320, 420], dtype=np.uint16)
    las.PredInstance_SAT = np.array([1, 2, 0, 2], dtype=np.uint16)
    las.PredInstance_FM = np.array([5, 6, 0, 6], dtype=np.uint16)
    las.species_id_FM = np.array([4, 5, 255, 6], dtype=np.uint8)
    las.species_prob_FM = np.array([0.1, 0.2, 0.3, 0.4], dtype=np.float32)
    las.PredSemantic_FM = np.array([7, 8, 9, 10], dtype=np.uint16)
    las.PredScore_FM = np.array([0.9, 0.8, 0.7, 0.6], dtype=np.float32)
    las.write(path)


class SpecialColoringLayoutTests(unittest.TestCase):
    def test_special_coloring_attribute_names_use_sat_and_fm_defaults(self) -> None:
        self.assertEqual(
            build_color_attribute_names(["PredInstance", "PredInstance_FM"]),
            ["coloring_id_sat", "coloring_id_fm"],
        )
        self.assertEqual(
            build_color_attribute_names(["PredInstance_SAT", "PredInstance_FoMa"]),
            ["coloring_id_sat", "coloring_id_fm"],
        )
        self.assertEqual(
            build_color_attribute_names(["PredInstance", "PredInstance_SAT"]),
            ["coloring_id_sat", "coloring_id_sat_2"],
        )

    def test_special_coloring_preserves_full_layout_for_potreeconverter(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            source_path = temp_path / "8120.las"
            outdir = temp_path / "potree"
            write_segmented_las(source_path)

            captured: dict[str, object] = {}

            def build_command(sources: list[str], attributes: list[str]) -> list[str]:
                captured["attributes"] = list(attributes)
                command = ["PotreeConverter", *sources, "-o", str(outdir)]
                for attribute in attributes:
                    command.extend(["--attributes", attribute])
                return command

            def run_command(command: list[str]) -> str:
                captured["command"] = list(command)
                colored_sources = list(Path(command[1]).glob("*.las"))
                self.assertEqual(len(colored_sources), 1)

                with laspy.open(colored_sources[0]) as reader:
                    dimensions = list(reader.header.point_format.dimension_names)
                    extra_dtypes = {
                        dim.name: dim.dtype
                        for dim in reader.header.point_format.extra_dimensions
                    }

                self.assertIn("scan_angle_rank", dimensions)
                self.assertEqual(extra_dtypes["PredInstance_SAT"], np.dtype("uint16"))
                self.assertEqual(extra_dtypes["PredInstance_FM"], np.dtype("uint16"))
                self.assertEqual(extra_dtypes["species_id_FM"], np.dtype("uint8"))
                self.assertEqual(extra_dtypes["species_prob_FM"], np.dtype("float32"))
                self.assertEqual(extra_dtypes["PredSemantic_FM"], np.dtype("uint16"))
                self.assertEqual(extra_dtypes["PredScore_FM"], np.dtype("float32"))
                self.assertEqual(extra_dtypes["coloring_id_sat"], np.dtype("uint16"))
                self.assertEqual(extra_dtypes["coloring_id_fm"], np.dtype("uint16"))
                return "converted"

            stdout = run_special_coloring_conversion(
                sources=[str(source_path)],
                outdir=outdir,
                attributes=[],
                instance_attributes=["PredInstance_SAT", "PredInstance_FM"],
                palette_name="candy",
                n_colors=10,
                n_neighbors=2,
                ground_instance_id=0,
                ground_color="#808080",
                write_sidecar_json=False,
                generate_page=None,
                build_command=build_command,
                run_command=run_command,
            )

            self.assertEqual(stdout, "converted")
            self.assertEqual(captured["attributes"], [])
            self.assertNotIn("--attributes", captured["command"])


if __name__ == "__main__":
    unittest.main()
