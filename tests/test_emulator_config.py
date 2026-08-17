from __future__ import annotations

import tempfile
import unittest
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from flask import Flask

from app.emulator_config import MAME_ROM_PATH, configured_emulator, emulator_command, emulator_status, profile_machine
from app.hardware_profiles import hardware_catalogue, normalise_hardware_profile
from app.operations import OperationRegistry
from app.disk_service import DiskService
from app.routes.images import create_images_blueprint
from app.routes.tools import clean_emulator_output, create_tools_blueprint


class EmulatorConfigurationTests(unittest.TestCase):
    def test_electron_uses_patched_elkulator_by_default(self):
        session = SimpleNamespace(hardware_profile={"machine": "electron", "emulator": "auto"}, target_hardware="electron-plus3")
        self.assertEqual(profile_machine(session), "electron")
        self.assertEqual(configured_emulator(session).identifier, "elkulator-pi1mhz")

    def test_bbc_uses_bem_by_default(self):
        session = SimpleNamespace(hardware_profile={"machine": "bbc-b", "emulator": "auto"}, target_hardware="bbc-master")
        self.assertEqual(configured_emulator(session).identifier, "b-em")

    def test_incompatible_choice_falls_back_to_the_machine_default(self):
        session = SimpleNamespace(hardware_profile={"machine": "archimedes", "emulator": "elkulator-pi1mhz"}, target_hardware="risc-os")
        self.assertEqual(configured_emulator(session).identifier, "mame")

    @patch("app.emulator_config.subprocess.run")
    @patch("app.emulator_config.Path.is_file", return_value=True)
    def test_archimedes_firmware_is_audited_from_the_bundled_rom_path(self, _available, run):
        run.return_value = SimpleNamespace(returncode=0, stdout="romset aa310 is good", stderr="")
        session = SimpleNamespace(hardware_profile={"machine": "archimedes", "emulator": "mame"}, target_hardware="risc-os")
        status = emulator_status(session)
        self.assertTrue(status["available"])
        self.assertEqual(
            run.call_args.args[0],
            ["/usr/games/mame", "-rompath", MAME_ROM_PATH, "-verifyroms", "aa310"],
        )

    @patch("app.emulator_config.emulator_status", return_value={"available": True})
    @patch("app.emulator_config.Path.is_file", return_value=True)
    def test_archimedes_command_uses_the_bundled_rom_path(self, _available, _status):
        session = SimpleNamespace(hardware_profile={"machine": "archimedes", "emulator": "mame"}, target_hardware="risc-os")
        command, cwd = emulator_command(session, "/work/game.adf")
        self.assertEqual(command[:4], ["/usr/games/mame", "-rompath", MAME_ROM_PATH, "aa310"])
        self.assertEqual(cwd, "/app")

    @patch("app.emulator_config.emulator_status", return_value={"available": True})
    @patch("app.emulator_config.Path.is_file", return_value=True)
    def test_native_archimedes_window_retains_host_audio(self, _available, _status):
        session = SimpleNamespace(
            hardware_profile={"machine": "archimedes", "emulator": "mame"},
            target_hardware="risc-os",
        )
        command, cwd = emulator_command(
            session,
            "/work/game.adf",
            interactive=True,
            native=True,
        )
        self.assertNotIn("-sound", command)
        self.assertIn("-video", command)
        self.assertEqual(cwd, str(Path(MAME_ROM_PATH).parent))

    @patch("app.emulator_config.Path.is_file", return_value=True)
    def test_bem_command_selects_the_requested_bbc_model(self, _available):
        with tempfile.TemporaryDirectory() as temporary:
            session = SimpleNamespace(hardware_profile={"machine": "master", "emulator": "auto", "emulatorBoot": "boot"}, target_hardware="bbc-master", path=Path(temporary) / "image.adf")
            command, cwd = emulator_command(session, "/work/game.adf")
        self.assertEqual(command[:10], ["timeout", "--signal=TERM", "--kill-after=2", "8", "env", "ALSA_CONFIG_PATH=/app/alsa-null.conf", "ALSOFT_DRIVERS=null", "xvfb-run", "-a", "/opt/b-em/b-em"])
        self.assertIn("-m10", command)
        self.assertIn("-autoboot", command)
        self.assertEqual(cwd, "/opt/b-em")

    @patch("app.emulator_config.Path.is_file", return_value=True)
    def test_elkulator_command_uses_the_patched_build_and_autoboot(self, _available):
        session = SimpleNamespace(hardware_profile={"machine": "electron", "emulator": "auto", "emulatorBoot": "boot"}, target_hardware="electron-plus3")
        command, cwd = emulator_command(session, "/work/game.ssd")
        self.assertEqual(command[:10], ["timeout", "--signal=TERM", "--kill-after=2", "8", "env", "ALSA_CONFIG_PATH=/app/alsa-null.conf", "ALSOFT_DRIVERS=null", "xvfb-run", "-a", "/opt/elkulator/profiles/base/elkulator"])
        self.assertIn("-autoboot", command)
        self.assertEqual(cwd, "/opt/elkulator/profiles/base")

    @patch("app.emulator_config.Path.is_file", return_value=True)
    def test_elkulator_whole_mmb_uses_pi1mhz_sd_and_mmfs_rom(self, _available):
        session = SimpleNamespace(
            hardware_profile={
                "machine": "electron", "emulator": "auto", "emulatorBoot": "boot",
                "filingSystem": "mmfs", "mmfsBuild": "unpaged", "addons": ["mmfs"],
            },
            target_hardware="auto", emulator_media_kind="mmfs-sd",
        )
        command, cwd = emulator_command(session, "/work/mmfs-card.img")
        self.assertIn("PI1MHZ_MAILBOX=live", command)
        self.assertIn("PI1MHZ_SD_IMAGE=/work/mmfs-card.img", command)
        self.assertIn("/opt/elkulator/roms/EMMFS.rom", command)
        self.assertIn("-autokeys", command)
        self.assertNotIn("-disc", command)
        self.assertEqual(cwd, "/opt/elkulator/profiles/base")

    @patch("app.emulator_config.Path.is_file", return_value=True)
    def test_interactive_elkulator_uses_the_shared_browser_display(self, _available):
        session = SimpleNamespace(hardware_profile={"machine": "electron", "emulator": "auto"}, target_hardware="auto")
        command, _cwd = emulator_command(session, "/work/game.ssd", interactive=True)
        self.assertIn("DISPLAY=:99", command)
        self.assertNotIn("xvfb-run", command)
        self.assertEqual(command[3], "900")

    @patch("app.emulator_config.Path.is_file", return_value=True)
    def test_native_interactive_elkulator_uses_the_host_display(self, _available):
        session = SimpleNamespace(
            hardware_profile={"machine": "electron", "emulator": "auto"},
            target_hardware="auto",
        )
        command, cwd = emulator_command(
            session,
            "/work/game.ssd",
            interactive=True,
            native=True,
        )
        self.assertEqual(command[0], "/opt/elkulator/profiles/base/elkulator")
        self.assertNotIn("DISPLAY=:99", command)
        self.assertNotIn("timeout", command)
        self.assertEqual(cwd, "/opt/elkulator/profiles/base")

    @patch("app.emulator_config.Path.is_file", return_value=True)
    def test_electron_additions_drive_elkulator_variant_ram_and_tube(self, _available):
        session = SimpleNamespace(hardware_profile={
            "machine": "electron", "emulator": "auto",
            "addons": ["electron-plus1", "electron-ap4", "electron-ap5", "electron-swram-64", "electron-mrb", "tube-6502"],
        }, target_hardware="electron-plus3")
        command, cwd = emulator_command(session, "/work/game.ssd")
        self.assertIn("/opt/elkulator/profiles/plus1-ap4-mrb/elkulator", command)
        self.assertEqual(command.count("-ram"), 4)
        self.assertIn("-tube6502", command)
        self.assertEqual(cwd, "/opt/elkulator/profiles/plus1-ap4-mrb")

    def test_expected_headless_shutdown_noise_is_removed(self):
        output = "\n".join([
            "Loading /opt/elkulator/roms/RHPLUS133.rom in bank 12",
            "ALSA lib confmisc.c:855:(parse_card) cannot find card '0'",
            "AP5 Tube: external 3MHz 65C02 enabled",
            "X connection to :99 broken (explicit kill or server shutdown).",
        ])
        self.assertEqual(clean_emulator_output(output), "\n".join([
            "Loading /opt/elkulator/roms/RHPLUS133.rom in bank 12",
            "AP5 Tube: external 3MHz 65C02 enabled",
        ]))

    @patch("app.emulator_config.Path.is_file", return_value=True)
    def test_rh_expansions_enable_plus1_hardware_and_load_the_verified_rom(self, _available):
        session = SimpleNamespace(hardware_profile={
            "machine": "electron", "emulator": "auto",
            "addons": ["electron-rh-plus1", "electron-rh-plus2"],
        }, target_hardware="auto")
        command, cwd = emulator_command(session, "/work/game.ssd")
        self.assertIn("/opt/elkulator/profiles/plus1/elkulator", command)
        self.assertIn("-rom", command)
        self.assertIn("12", command)
        self.assertIn("/opt/elkulator/roms/RHPLUS133.rom", command)
        self.assertEqual(cwd, "/opt/elkulator/profiles/plus1")

    @patch("app.emulator_config.emulator_status", return_value={"available": True})
    @patch("app.emulator_config.Path.is_file", return_value=True)
    def test_archimedes_additions_become_mame_podules(self, _available, _status):
        session = SimpleNamespace(hardware_profile={"machine": "archimedes", "addons": ["arch-scsi", "arch-midi"]}, target_hardware="risc-os")
        command, _cwd = emulator_command(session, "/work/game.adf")
        self.assertIn("-podule0", command)
        self.assertIn("midi_aka16", command)
        self.assertIn("-podule2", command)
        self.assertIn("scsi_aka31", command)

    def test_hardware_catalogue_has_common_machine_families(self):
        machines = {row["id"] for row in hardware_catalogue()["machines"]}
        self.assertEqual(machines, {"electron", "bbc-b", "bbc-b-plus", "master", "archimedes"})

    def test_hardware_profile_rejects_incompatible_and_conflicting_additions(self):
        with self.assertRaisesRegex(ValueError, "cannot be fitted"):
            normalise_hardware_profile({"machine": "bbc-b", "addons": ["electron-plus1"]})
        with self.assertRaisesRegex(ValueError, "Choose no more than 1"):
            normalise_hardware_profile({"machine": "bbc-b", "addons": ["bbc-8271", "bbc-acorn1770"]})

    def test_electron_beebscsi_requires_ap5_and_carrier(self):
        with self.assertRaisesRegex(ValueError, "requires PRES Advanced Plus 5"):
            normalise_hardware_profile({"machine": "electron", "addons": ["beebscsi"]})
        with self.assertRaisesRegex(ValueError, "requires Acorn Plus 1"):
            normalise_hardware_profile({"machine": "electron", "addons": ["electron-ap5", "beebscsi"]})
        profile = normalise_hardware_profile({
            "machine": "electron",
            "addons": ["electron-plus1", "electron-plus3", "electron-ap5", "electron-mrb", "beebscsi"],
        })
        self.assertEqual(profile["machine"], "electron")
        self.assertFalse(profile["tube"])

    def test_rh_plus_chassis_can_be_combined_and_satisfy_ap5(self):
        profile = normalise_hardware_profile({
            "machine": "electron",
            "addons": ["electron-rh-plus1", "electron-rh-plus2", "electron-ap5", "beebscsi"],
        })
        self.assertIn("electron-rh-plus1", profile["addons"])
        self.assertIn("electron-rh-plus2", profile["addons"])

    def test_pitube_direct_is_available_to_every_compatible_tube_host(self):
        catalogue = hardware_catalogue()
        pitube = next(row for row in catalogue["addons"] if row["id"] == "tube-pitube-direct")
        self.assertEqual(set(pitube["machines"]), {"electron", "bbc-b", "bbc-b-plus", "master"})
        for machine in ("bbc-b", "bbc-b-plus", "master"):
            profile = normalise_hardware_profile({"machine": machine, "addons": ["tube-pitube-direct"]})
            self.assertTrue(profile["tube"])

    def test_electron_pitube_direct_requires_an_ap5_tube_interface(self):
        with self.assertRaisesRegex(ValueError, "requires PRES Advanced Plus 5"):
            normalise_hardware_profile({"machine": "electron", "addons": ["tube-pitube-direct"]})
        profile = normalise_hardware_profile({
            "machine": "electron",
            "addons": ["electron-rh-plus1", "electron-ap5", "tube-pitube-direct"],
        })
        self.assertTrue(profile["tube"])

    def test_acorn_and_pres_plus1_replacements_conflict(self):
        with self.assertRaisesRegex(ValueError, "cannot be fitted"):
            normalise_hardware_profile({"machine": "electron", "addons": ["electron-plus1", "electron-ap1"]})

    def test_editor_status_uses_managed_profile(self):
        service = Mock()
        service.get.return_value = SimpleNamespace(
            hardware_profile={"machine": "bbc-b", "emulator": "mame"},
            target_hardware="bbc-master", path=Path("/work/test.ssd"),
        )
        app = Flask(__name__)
        app.register_blueprint(create_tools_blueprint(service, OperationRegistry()))
        with patch("app.routes.tools.emulator_status", return_value={"available": True, "label": "MAME Acorn systems", "configuredBy": "managed workbench profile"}), patch("app.routes.tools.emulator_command", return_value=(["/usr/games/mame", "bbcb"], "/app")):
            result = app.test_client().get("/api/images/test/editor-emulator").get_json()
        self.assertTrue(result["available"])
        self.assertEqual(result["command"], "/usr/games/mame bbcb")
        self.assertEqual(result["configuredBy"], "managed workbench profile")

    def test_editor_status_uses_the_effective_workbench_profile(self):
        service = Mock()
        service.get.return_value = SimpleNamespace(
            hardware_profile={"machine": "bbc-b", "emulator": "b-em"},
            target_hardware="auto", path=Path("/work/test.ssd"),
        )
        app = Flask(__name__)
        app.register_blueprint(create_tools_blueprint(service, OperationRegistry()))
        profile = {"machine": "electron", "emulator": "elkulator-pi1mhz", "addons": []}
        with patch("app.emulator_config.Path.is_file", return_value=True):
            result = app.test_client().get(
                "/api/images/test/editor-emulator",
                query_string={"hardwareProfile": json.dumps(profile), "basic": "true"},
            ).get_json()
        self.assertEqual(result["id"], "elkulator-pi1mhz")
        self.assertEqual(result["machine"], "electron")
        self.assertTrue(result["parentMountable"])
        self.assertTrue(result["isolatedBasic"])

    def test_isolated_basic_run_builds_a_temporary_bootable_disk(self):
        with tempfile.TemporaryDirectory() as temporary:
            service = DiskService(temporary)
            session = service.create_blank("ssd", "SOURCE")
            from oaknut.basic import tokenise
            source_path = Path(temporary) / "program.bin"
            source_path.write_bytes(tokenise('10 PRINT "EDITOR TEST"\n20 END'))
            service.put(session, None, "$.TEST", source_path, "0x1900", "0x1900", None)
            app = Flask(__name__)
            app.register_blueprint(create_tools_blueprint(service, OperationRegistry()))
            with patch("app.routes.tools.run_emulator_process") as run:
                run.return_value = SimpleNamespace(returncode=124, stdout="", stderr="")
                response = app.test_client().post(f"/api/images/{session.id}/editor-emulator", json={
                    "path": "$.TEST", "mode": "isolated-basic",
                    "source": '10 PRINT "CHANGED"\n20 END',
                    "hardwareProfile": {
                        "machine": "electron", "emulator": "elkulator-pi1mhz",
                        "filingSystem": "dfs", "page": "E00", "addons": [],
                    },
                })
                command = run.call_args.args[0]
        self.assertEqual(response.status_code, 200, response.get_data(as_text=True))
        self.assertIn("/opt/elkulator/profiles/base/elkulator", command)
        self.assertIn("-disc", command)
        self.assertTrue(str(command[command.index("-disc") + 1]).endswith("blank.ssd"))

    def test_mmb_slot_run_extracts_only_the_selected_disk_for_the_emulator(self):
        with tempfile.TemporaryDirectory() as temporary:
            service = DiskService(temporary)
            mmb = service.create_blank("mmb", "COLLECTION")
            disk = service.create_blank("ssd", "GAME")
            service.insert_slot_from_session(mmb, 7, disk, None)
            app = Flask(__name__)
            app.register_blueprint(create_tools_blueprint(service, OperationRegistry()))
            with patch("app.routes.tools.run_emulator_process") as run:
                run.return_value = SimpleNamespace(returncode=124, stdout="", stderr="")
                response = app.test_client().post(f"/api/images/{mmb.id}/editor-emulator", json={
                    "path": "", "slot": 7, "mode": "slot-mount",
                    "hardwareProfile": {
                        "machine": "bbc-b", "emulator": "b-em",
                        "filingSystem": "mmfs", "addons": [],
                    },
                })
                command = run.call_args.args[0]
                media = Path(command[command.index("-disc") + 1])
            self.assertEqual(response.status_code, 200, response.get_data(as_text=True))
            self.assertEqual(media.suffix, ".ssd")
            self.assertIn("mmb-slot-007-", media.name)
            self.assertFalse(media.exists())

    def test_whole_mmb_status_explains_the_missing_managed_adapter(self):
        with tempfile.TemporaryDirectory() as temporary:
            service = DiskService(temporary)
            mmb = service.create_blank("mmb", "COLLECTION")
            app = Flask(__name__)
            app.register_blueprint(create_tools_blueprint(service, OperationRegistry()))
            with patch("app.emulator_config.Path.is_file", return_value=True):
                response = app.test_client().get(
                    f"/api/images/{mmb.id}/editor-emulator",
                    query_string={"hardwareProfile": json.dumps({
                        "machine": "bbc-b", "emulator": "b-em", "addons": [],
                    })},
                )
            result = response.get_json()
        self.assertEqual(response.status_code, 200)
        self.assertFalse(result["available"])
        self.assertIn("managed Pi1MHz raw-SD adapter", result["parentMessage"])

    def test_whole_mmb_status_accepts_electron_mmfs_adapter(self):
        with tempfile.TemporaryDirectory() as temporary:
            service = DiskService(temporary)
            mmb = service.create_blank("mmb", "COLLECTION")
            app = Flask(__name__)
            app.register_blueprint(create_tools_blueprint(service, OperationRegistry()))
            profile = {
                "machine": "electron", "emulator": "elkulator-pi1mhz",
                "filingSystem": "mmfs", "mmfsBuild": "unpaged", "addons": ["mmfs"],
            }
            with patch("app.routes.tools.emulator_status", return_value={
                "available": True, "machine": "electron", "label": "Elkulator",
                "message": "ready", "id": "elkulator-pi1mhz", "debugger": "elkulator-debug",
                "configuredBy": "managed workbench profile",
            }), patch("app.emulator_config.Path.is_file", return_value=True):
                response = app.test_client().get(
                    f"/api/images/{mmb.id}/editor-emulator",
                    query_string={"hardwareProfile": json.dumps(profile)},
                )
        self.assertEqual(response.status_code, 200)
        result = response.get_json()
        self.assertTrue(result["available"])
        self.assertTrue(result["parentMountable"])
        self.assertEqual(result["mediaTarget"], "whole-mmb")

    def test_hardware_profile_retains_only_bounded_managed_choices(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        service = Mock()
        session = SimpleNamespace(kind="dfs", hardware_profile={}, target_hardware="auto")
        service.get.return_value = session
        service.summary.return_value = {"id": "test", "kind": "dfs", "hardwareProfile": session.hardware_profile}
        app = Flask(__name__)
        app.register_blueprint(create_images_blueprint(service, Path(temporary.name), OperationRegistry()))
        response = app.test_client().patch("/api/images/test/hardware-profile", json={
            "name": "Test profile", "machine": "electron", "filingSystem": "adfs",
            "addons": ["electron-plus3"],
            "emulator": "elkulator-pi1mhz", "debugger": "elkulator-debug",
            "emulatorRam": "64K", "emulatorBoot": "boot",
            "fileEmulatorCommand": "/untrusted/tool {file}",
        })
        self.assertEqual(response.status_code, 200)
        self.assertEqual(session.hardware_profile["emulator"], "elkulator-pi1mhz")
        self.assertEqual(session.hardware_profile["debugger"], "elkulator-debug")
        self.assertEqual(session.hardware_profile["addons"], ["electron-plus3"])
        self.assertNotIn("fileEmulatorCommand", session.hardware_profile)

    def test_hardware_profile_catalogue_endpoint(self):
        app = Flask(__name__)
        app.register_blueprint(create_images_blueprint(Mock(), Path("/tmp"), OperationRegistry()))
        data = app.test_client().get("/api/hardware-profiles").get_json()
        self.assertIn("machines", data)
        self.assertTrue(any(row["id"] == "bbc-b-plus" for row in data["machines"]))


if __name__ == "__main__":
    unittest.main()
