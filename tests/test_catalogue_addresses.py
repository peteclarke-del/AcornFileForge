from __future__ import annotations

import unittest

from app.acorn_metadata import engine_address, parse_address
from app.menu_records import menu_page_field, normalise_page
from app.errors import DiskError
from app.routes.common import catalogue_address


class AcornAddressNotationTests(unittest.TestCase):
    """Acorn addresses are hexadecimal however the user chooses to write them."""

    def test_the_three_accepted_notations_mean_one_number(self) -> None:
        for text in ("1900", "&1900", "0x1900", "&1900 ", " 1900"):
            with self.subTest(text=text):
                self.assertEqual(parse_address(text), 0x1900)

    def test_case_is_not_significant(self) -> None:
        self.assertEqual(parse_address("ffff1900"), parse_address("FFFF1900"))
        self.assertEqual(parse_address("0XABCD"), 0xABCD)

    def test_the_full_thirty_two_bit_range_is_accepted(self) -> None:
        self.assertEqual(parse_address("FFFFFFFF"), 0xFFFFFFFF)
        self.assertEqual(parse_address("0"), 0)

    def test_values_that_are_not_addresses_are_rejected(self) -> None:
        for text in ("", "   ", "19 00", "&&1900", "0x", "123456789", "19g0", "-1"):
            with self.subTest(text=text):
                with self.assertRaises(ValueError):
                    parse_address(text)


class EngineAddressTests(unittest.TestCase):
    """The engine reads a bare number as decimal, so it is never given one."""

    def test_every_notation_becomes_one_explicit_hexadecimal_value(self) -> None:
        for text in ("1900", "&1900", "0x1900"):
            with self.subTest(text=text):
                self.assertEqual(engine_address(text), "0x1900")

    def test_a_bare_value_is_not_passed_through_as_decimal(self) -> None:
        # Verbatim, "1900" would reach the engine as one thousand nine hundred.
        self.assertNotEqual(engine_address("1900"), "1900")
        self.assertEqual(int(engine_address("1900"), 16), 0x1900)

    def test_zero_is_emitted_in_the_same_explicit_form(self) -> None:
        self.assertEqual(engine_address("00000000"), "0x0")
        self.assertEqual(engine_address("&0"), "0x0")


class RouteAddressNormalisationTests(unittest.TestCase):
    """The boundary helper used by every route that accepts a typed address."""

    def test_each_notation_normalises_to_the_same_engine_value(self) -> None:
        for text in ("1900", "&1900", "0x1900", "  &1900  "):
            with self.subTest(text=text):
                self.assertEqual(catalogue_address(text), "0x1900")

    def test_an_absent_address_stays_absent_rather_than_becoming_zero(self) -> None:
        """Importing without an address must not invent one."""
        for value in (None, "", "   "):
            with self.subTest(value=value):
                self.assertIsNone(catalogue_address(value))

    def test_an_invalid_address_is_refused_with_guidance(self) -> None:
        with self.assertRaises(DiskError) as caught:
            catalogue_address("nineteen hundred")
        message = str(caught.exception)
        self.assertIn("not a valid Acorn address", message)
        self.assertIn("&1900", message)
        self.assertIn("0x1900", message)

    def test_the_refusal_names_the_value_that_was_rejected(self) -> None:
        with self.assertRaises(DiskError) as caught:
            catalogue_address("12345678900")
        self.assertIn("12345678900", str(caught.exception))


class MenuPageConventionTests(unittest.TestCase):
    """PAGE keeps its own high-byte convention and is not an address field.

    Universal Menu stores PAGE as the high byte, so ``19`` there means &1900.
    Address fields have no such shorthand: ``19`` is &0019. These two rules
    must not be merged.
    """

    def test_menu_page_expands_a_high_byte_but_an_address_does_not(self) -> None:
        self.assertEqual(normalise_page("19"), "1900")
        self.assertEqual(normalise_page("1900"), "1900")
        self.assertEqual(normalise_page("&E00"), "E00")
        self.assertEqual(parse_address("19"), 0x19)

    def test_menu_page_round_trips_through_its_stored_high_byte(self) -> None:
        for written in ("19", "1900", "&1900"):
            with self.subTest(written=written):
                self.assertEqual(normalise_page(menu_page_field(written)), "1900")

    def test_a_page_is_stored_as_its_high_byte(self) -> None:
        """The database holds &E00 as "E"; its BASIC reader appends the 00."""
        self.assertEqual(menu_page_field("E00"), "E")
        self.assertEqual(menu_page_field("1900"), "19")
        self.assertEqual(normalise_page("E"), "E00")

    def test_a_page_that_is_not_a_whole_page_boundary_is_kept_complete(self) -> None:
        """Only a trailing 00 may be dropped, or the address would change."""
        self.assertEqual(menu_page_field("1234"), "1234")


if __name__ == "__main__":
    unittest.main()
