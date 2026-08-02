from __future__ import annotations

import unittest

from app.menu_interpreter import decode_basic, interpret_menu_program


def basic_program(lines: list[tuple[int, bytes]]) -> bytes:
    result = bytearray()
    for number, body in lines:
        result.extend(b"\x0D" + number.to_bytes(2, "big") + bytes((len(body) + 4,)) + body)
    result.extend(b"\x0D\xFF")
    return bytes(result)


class MenuInterpreterTests(unittest.TestCase):
    def test_interprets_universal_menu_display_setup(self):
        program = basic_program(
            [
                (10, b"\xEB1"),
                (20, b'D1$="GAMDATA":I1$="GAMINDX":D2$="PUBDATA":I2$="PUBINDX"'),
                (30, b"\xEF19,1,4,0,0,0:\xEF19,3,6,0,0,0"),
                (40, b"\xFFLOAD TXT2SCN"),
                (50, b"\xFB2:\xF1\x8A13)$&CD0:\xFB3"),
                (60, b"\xF1$&C86:\xF1STR$(MAX%)+\" Screens\""),
                (70, b"\xEF28,0,31,39,3"),
                (80, b"R%=26"),
            ]
        )
        helper = bytearray(256)
        banner = b"f0=EXIT,f3=DATA1/2,f5=Search,f7=AZ Jump\r"
        title = b"Universal Menu\r"
        helper[0x86 : 0x86 + len(banner)] = banner
        helper[0xD0 : 0xD0 + len(title)] = title

        result = interpret_menu_program(
            "UNIMENU",
            program,
            {"TXT2SCN": (0xC00, bytes(helper))},
        )

        self.assertTrue(result["supported"])
        self.assertEqual(result["mode"], 1)
        self.assertEqual((result["columns"], result["rows"]), (40, 32))
        self.assertEqual(result["palette"][1], "#0000ff")
        self.assertEqual(result["palette"][3], "#00ffff")
        self.assertEqual(result["textWindow"], {"left": 0, "bottom": 31, "right": 39, "top": 3})
        self.assertEqual(result["title"], {"text": "Universal Menu", "x": 13, "y": 0, "colour": 2})
        self.assertEqual(result["entries"]["pageSize"], 26)

    def test_binary_menu_is_reported_as_unsupported(self):
        result = interpret_menu_program("MENU", b"\x00\x01machine", {})

        self.assertFalse(result["supported"])
        self.assertIn("not tokenised BBC BASIC", result["reason"])

    def test_interprets_spi_game_menu_display_and_boot_flow(self):
        program = basic_program(
            [
                (10, b"\xEB1"),
                (20, b'G=OPENIN"GAMINDX":F=OPENIN"GAMDATA":P$="PUBDATA"'),
                (30, b"\xEF19,1,6,0,0,0:\xEF19,0,0,0,0,0"),
                (40, b'\xFB2:\xF1\x8A8)"ELECTRON SDI GAME MENU"'),
                (50, b'FUNK$="f0=EXIT,f3=Game,f5=Publisher,f7=A-Z Jump":\xF1FUNK$'),
                (60, b"\xEF28,0,31,39,3"),
                (70, b"\xF2OSGBPB"),
                (80, b'\xFF"DIN 0 "+G$'),
            ]
        )

        result = interpret_menu_program("GAMECOL", program, {})

        self.assertTrue(result["supported"])
        self.assertEqual(result["kind"], "bbc-basic-spi-game-menu")
        self.assertEqual(result["title"]["text"], "ELECTRON SDI GAME MENU")
        self.assertEqual(result["title"]["x"], 8)
        self.assertEqual(result["palette"][1], "#00ffff")
        self.assertFalse(result["status"]["visible"])
        self.assertEqual(result["launch"]["command"], "*EXEC !BOOT")

    def test_decoder_rejects_truncated_line(self):
        self.assertIsNone(decode_basic(b"\x0D\x00\x0A\x20short"))


if __name__ == "__main__":
    unittest.main()
