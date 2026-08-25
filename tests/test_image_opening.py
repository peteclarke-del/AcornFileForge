from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from app.rom_components import write_combined_rom


class ImageOpeningTests(unittest.TestCase):
    def test_empty_native_rom_component_set_is_rejected(self):
        with TemporaryDirectory() as temporary:
            output = Path(temporary) / "combined.rom"

            with self.assertRaisesRegex(ValueError, "at least one"):
                write_combined_rom([], output)

    def test_unknown_native_rom_layout_is_rejected_before_writing(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            component = root / "component.rom"
            component.write_bytes(b"data")
            output = root / "combined.rom"

            with self.assertRaisesRegex(ValueError, "linear, two-chip or four-chip"):
                write_combined_rom([component], output, "byte-interleaved-many")

            self.assertFalse(output.exists())

    def test_native_rom_components_use_the_reviewed_interleaving_plan(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            first = root / "rom0.bin"
            second = root / "rom1.bin"
            first.write_bytes(b"ac")
            second.write_bytes(b"bd")
            output = root / "combined.rom"
            write_combined_rom([first, second], output, "byte-interleaved-2")

            self.assertEqual(output.read_bytes(), b"abcd")

    def test_native_rom_layout_component_count_must_match(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            components = []
            for index in range(4):
                component = root / f"rom{index}.bin"
                component.write_bytes(bytes([index]))
                components.append(component)

            with self.assertRaisesRegex(ValueError, "requires exactly 2"):
                write_combined_rom(
                    components,
                    root / "combined.rom",
                    "byte-interleaved-2",
                )

            self.assertFalse((root / "combined.rom").exists())


if __name__ == "__main__":
    unittest.main()
