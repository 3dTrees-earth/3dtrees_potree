from __future__ import annotations

import json
import struct
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from attribute_node_stats import write_attribute_node_stats


def hierarchy_entry(node_type: int, child_mask: int, num_points: int, byte_offset: int, byte_size: int) -> bytes:
    return struct.pack("<BBIqq", node_type, child_mask, num_points, byte_offset, byte_size)


def uncompressed_record(probability: float, species_id: int) -> bytes:
    return struct.pack("<iii", 0, 0, 0) + struct.pack("<fB", probability, species_id)


def metadata(encoding: str, first_chunk_size: int) -> dict:
    return {
        "encoding": encoding,
        "hierarchy": {"firstChunkSize": first_chunk_size},
        "attributes": [
            {
                "name": "position",
                "type": "int32",
                "numElements": 3,
                "elementSize": 4,
                "size": 12,
            },
            {
                "name": "species_prob",
                "type": "float",
                "numElements": 1,
                "elementSize": 4,
                "size": 4,
            },
            {
                "name": "species_id",
                "type": "uint8",
                "numElements": 1,
                "elementSize": 1,
                "size": 1,
            },
        ],
    }


class AttributeNodeStatsTests(unittest.TestCase):
    def test_writes_subtree_stats_for_uncompressed_octree(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            potree_dir = Path(temp_dir)
            root_payload = uncompressed_record(0.2, 1) + uncompressed_record(0.8, 2)
            child0_payload = uncompressed_record(0.9, 4)
            child1_payload = uncompressed_record(0.1, 2) + uncompressed_record(0.3, 2)
            octree = root_payload + child0_payload + child1_payload

            hierarchy = b"".join(
                [
                    hierarchy_entry(1, 0b00000011, 2, 0, len(root_payload)),
                    hierarchy_entry(1, 0, 1, len(root_payload), len(child0_payload)),
                    hierarchy_entry(1, 0, 2, len(root_payload) + len(child0_payload), len(child1_payload)),
                ]
            )

            (potree_dir / "metadata.json").write_text(
                json.dumps(metadata("UNCOMPRESSED", len(hierarchy))),
                encoding="utf-8",
            )
            (potree_dir / "hierarchy.bin").write_bytes(hierarchy)
            (potree_dir / "octree.bin").write_bytes(octree)

            sidecar_path = write_attribute_node_stats(potree_dir / "metadata.json")
            sidecar = json.loads(sidecar_path.read_text(encoding="utf-8"))

            self.assertEqual(sidecar["version"], 1)
            self.assertEqual(sidecar["scope"], "subtree")
            self.assertAlmostEqual(sidecar["nodes"]["r"]["species_prob"]["min"], 0.1, places=6)
            self.assertAlmostEqual(sidecar["nodes"]["r"]["species_prob"]["max"], 0.9, places=6)
            self.assertEqual(sidecar["nodes"]["r"]["species_id"]["values"], [1, 2, 4])
            self.assertEqual(sidecar["nodes"]["r0"]["species_id"]["values"], [4])
            self.assertEqual(sidecar["nodes"]["r1"]["species_id"]["values"], [2])

    def test_include_attributes_preserves_full_point_layout(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            potree_dir = Path(temp_dir)
            root_payload = uncompressed_record(0.2, 1) + uncompressed_record(0.8, 2)
            hierarchy = hierarchy_entry(1, 0, 2, 0, len(root_payload))

            (potree_dir / "metadata.json").write_text(
                json.dumps(metadata("UNCOMPRESSED", len(hierarchy))),
                encoding="utf-8",
            )
            (potree_dir / "hierarchy.bin").write_bytes(hierarchy)
            (potree_dir / "octree.bin").write_bytes(root_payload)

            sidecar_path = write_attribute_node_stats(
                potree_dir / "metadata.json",
                include_attributes={"species_prob"},
            )
            sidecar = json.loads(sidecar_path.read_text(encoding="utf-8"))

            self.assertEqual(sidecar["attributes"], ["species_prob"])
            self.assertAlmostEqual(sidecar["nodes"]["r"]["species_prob"]["min"], 0.2, places=6)
            self.assertAlmostEqual(sidecar["nodes"]["r"]["species_prob"]["max"], 0.8, places=6)
            self.assertNotIn("species_id", sidecar["nodes"]["r"])

    def test_writes_subtree_stats_for_brotli_octree(self) -> None:
        try:
            import brotli
        except ImportError:
            self.skipTest("brotli is not installed")

        def brotli_payload(probabilities: list[float], species_ids: list[int]) -> bytes:
            positions = b"\0" * (16 * len(probabilities))
            prob_bytes = b"".join(struct.pack("<f", value) for value in probabilities)
            species_bytes = bytes(species_ids)
            return brotli.compress(positions + prob_bytes + species_bytes)

        with tempfile.TemporaryDirectory() as temp_dir:
            potree_dir = Path(temp_dir)
            root_payload = brotli_payload([0.2, 0.8], [1, 2])
            child0_payload = brotli_payload([0.9], [4])
            child1_payload = brotli_payload([0.1, 0.3], [2, 2])
            octree = root_payload + child0_payload + child1_payload

            hierarchy = b"".join(
                [
                    hierarchy_entry(1, 0b00000011, 2, 0, len(root_payload)),
                    hierarchy_entry(1, 0, 1, len(root_payload), len(child0_payload)),
                    hierarchy_entry(1, 0, 2, len(root_payload) + len(child0_payload), len(child1_payload)),
                ]
            )

            (potree_dir / "metadata.json").write_text(
                json.dumps(metadata("BROTLI", len(hierarchy))),
                encoding="utf-8",
            )
            (potree_dir / "hierarchy.bin").write_bytes(hierarchy)
            (potree_dir / "octree.bin").write_bytes(octree)

            sidecar_path = write_attribute_node_stats(potree_dir / "metadata.json")
            sidecar = json.loads(sidecar_path.read_text(encoding="utf-8"))

            self.assertEqual(sidecar["source"]["encoding"], "BROTLI")
            self.assertEqual(sidecar["nodes"]["r"]["species_id"]["values"], [1, 2, 4])
            self.assertAlmostEqual(sidecar["nodes"]["r0"]["species_prob"]["min"], 0.9, places=6)
            self.assertAlmostEqual(sidecar["nodes"]["r1"]["species_prob"]["max"], 0.3, places=6)

    def test_resolves_proxy_hierarchy_chunks(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            potree_dir = Path(temp_dir)
            root_payload = uncompressed_record(0.2, 1)
            child_payload = uncompressed_record(0.9, 4)
            octree = root_payload + child_payload

            first_chunk_size = 2 * 22
            proxy_chunk_offset = first_chunk_size
            proxy_chunk = hierarchy_entry(1, 0, 1, len(root_payload), len(child_payload))
            hierarchy = b"".join(
                [
                    hierarchy_entry(1, 0b00000001, 1, 0, len(root_payload)),
                    hierarchy_entry(2, 0, 1, proxy_chunk_offset, len(proxy_chunk)),
                    proxy_chunk,
                ]
            )

            (potree_dir / "metadata.json").write_text(
                json.dumps(metadata("UNCOMPRESSED", first_chunk_size)),
                encoding="utf-8",
            )
            (potree_dir / "hierarchy.bin").write_bytes(hierarchy)
            (potree_dir / "octree.bin").write_bytes(octree)

            sidecar_path = write_attribute_node_stats(potree_dir / "metadata.json")
            sidecar = json.loads(sidecar_path.read_text(encoding="utf-8"))

            self.assertEqual(sidecar["nodes"]["r"]["species_id"]["values"], [1, 4])
            self.assertEqual(sidecar["nodes"]["r0"]["species_id"]["values"], [4])


if __name__ == "__main__":
    unittest.main()
