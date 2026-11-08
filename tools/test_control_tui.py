import asyncio
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, Mock, patch

from tools import control_tui as tui


class PodmanStartupTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.machine_patch = patch.object(tui, "PODMAN_MACHINE", "telar-fabulas-dev")
        self.machine_patch.start()
        self.addCleanup(self.machine_patch.stop)
        self.app = tui.ControlSistemaApp()
        self.app.write_log = Mock()
        self.app.set_busy = Mock()
        self.app.refresh_status = AsyncMock()
        self.app.execute_command = AsyncMock(return_value=0)
        self.app.ensure_machine_connections = AsyncMock(return_value=True)
        socket_patch = patch.object(tui, "remove_stale_machine_socket")
        socket_patch.start()
        self.addCleanup(socket_patch.stop)

    def machines(self, *, running=False, provider="wsl", name="telar-fabulas-dev"):
        return (0, json.dumps([{"Name": name, "Running": running, "VMType": provider}]))

    async def test_wsl_directory_is_prepared_before_starting_project_machine(self):
        self.app.capture_command = Mock(side_effect=[self.machines(), (0, "[{}]"), (0, "telar"), (0, "NAME STATUS")])
        with patch.object(tui.platform, "system", return_value="Windows"):
            await self.app.start_podman()
        commands = [call.args[1] for call in self.app.execute_command.await_args_list]
        self.assertEqual(commands, [
            ["wsl.exe", "--distribution", "podman-telar-fabulas-dev", "--user", "root",
             "--exec", "mkdir", "-p", "/usr/share/containers/containers.conf.d"],
            ["podman", "machine", "start", "--update-connection=false", "telar-fabulas-dev"],
        ])
        self.assertEqual(self.app.capture_command.call_args.args[0][:3],
                         ["podman", "--connection", "telar-fabulas-dev"])
        self.app.set_busy.assert_called_with(False)

    async def test_failed_directory_preparation_prevents_start(self):
        self.app.capture_command = Mock(side_effect=[self.machines(), (0, "[{}]")])
        self.app.execute_command.return_value = 1
        with patch.object(tui.platform, "system", return_value="Windows"):
            await self.app.start_podman()
        self.app.execute_command.assert_awaited_once()
        self.app.set_busy.assert_called_with(False)

    async def test_missing_machine_never_falls_back_to_default(self):
        self.app.capture_command = Mock(return_value=self.machines(name="podman-machine-default"))
        await self.app.start_podman()
        self.app.execute_command.assert_not_awaited()
        self.assertTrue(any("No existe" in call.args[0] for call in self.app.write_log.call_args_list))

    async def test_running_machine_checks_connection_without_restarting(self):
        self.app.capture_command = Mock(side_effect=[self.machines(running=True), (0, "telar"), (0, "NAME STATUS")])
        await self.app.start_podman()
        self.app.execute_command.assert_not_awaited()
        self.assertIn("Podman y Compose listos", self.app.write_log.call_args.args[0])

    async def test_broken_connection_does_not_report_success(self):
        self.app.capture_command = Mock(side_effect=[self.machines(running=True), (125, "socket missing")])
        await self.app.start_podman()
        self.assertIn("no responde", self.app.write_log.call_args.args[0])
        self.app.execute_command.assert_not_awaited()

    async def test_working_podman_with_broken_compose_does_not_report_ready(self):
        self.app.capture_command = Mock(side_effect=[self.machines(running=True), (0, "telar"),
                                                   (1, "named pipe missing")])
        await self.app.start_podman()
        self.assertIn("Compose no está disponible", self.app.write_log.call_args.args[0])
        self.app.execute_command.assert_not_awaited()

    async def test_non_wsl_provider_does_not_run_wsl(self):
        self.app.capture_command = Mock(side_effect=[self.machines(provider="hyperv"), (0, "[{}]"),
                                                   (0, "telar"), (0, "NAME STATUS")])
        with patch.object(tui.platform, "system", return_value="Windows"):
            await self.app.start_podman()
        self.app.execute_command.assert_awaited_once_with(
            "Arrancar podman",
            ["podman", "machine", "start", "--update-connection=false", "telar-fabulas-dev"]
        )


class PodmanConnectionRecoveryTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        machine_patch = patch.object(tui, "PODMAN_MACHINE", "telar-fabulas-dev")
        machine_patch.start()
        self.addCleanup(machine_patch.stop)
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.directory = Path(directory.name)
        self.identity = self.directory / "machine-key"
        self.identity.write_text("test fixture", encoding="utf-8")
        self.config = self.directory / "telar-fabulas-dev.json"
        self.config.write_text(json.dumps({
            "Name": "telar-fabulas-dev", "HostUser": {"UID": 1007},
        }), encoding="utf-8")
        self.machine = {
            "Name": "telar-fabulas-dev",
            "ConfigDir": {"Path": str(self.directory)},
            "SSHConfig": {
                "IdentityPath": str(self.identity), "Port": 43210, "RemoteUsername": "devuser",
            },
        }
        self.app = tui.ControlSistemaApp()
        self.app.write_log = Mock()
        self.app.set_busy = Mock()
        self.app.refresh_status = AsyncMock()
        self.app.execute_command = AsyncMock(return_value=0)
        socket_patch = patch.object(tui, "remove_stale_machine_socket")
        socket_patch.start()
        self.addCleanup(socket_patch.stop)

    def connections(self, *extra_names):
        return (0, json.dumps([
            {"Name": "podman-machine-default", "Default": True},
            *({"Name": name, "Default": False} for name in extra_names),
        ]))

    def inspect(self):
        return (0, json.dumps([self.machine]))

    async def test_missing_connections_recovered_for_running_and_stopped_machines(self):
        for running in (True, False):
            with self.subTest(running=running):
                self.app.execute_command.reset_mock()
                self.app.capture_command = Mock(side_effect=[
                    (0, json.dumps([{"Name": "telar-fabulas-dev", "Running": running, "VMType": "hyperv"}])),
                    self.connections(), self.inspect(),
                    *([self.inspect()] if not running else []),
                    (0, "telar"), (0, "NAME STATUS"),
                ])
                with patch.object(tui.platform, "system", return_value="Windows"):
                    await self.app.start_podman()
                commands = [call.args[1] for call in self.app.execute_command.await_args_list]
                self.assertEqual(commands[:2], [
                    ["podman", "system", "connection", "add", "--identity", str(self.identity),
                     "telar-fabulas-dev", "ssh://devuser@127.0.0.1:43210/run/user/1007/podman/podman.sock"],
                    ["podman", "system", "connection", "add", "--identity", str(self.identity),
                     "telar-fabulas-dev-root", "ssh://root@127.0.0.1:43210/run/podman/podman.sock"],
                ])
                self.assertEqual(len(commands), 2 if running else 3)
                if not running:
                    self.assertEqual(commands[-1], ["podman", "machine", "start",
                                                   "--update-connection=false", "telar-fabulas-dev"])
                self.assertIn("Podman y Compose listos", self.app.write_log.call_args.args[0])

    async def test_existing_connections_are_not_rewritten(self):
        self.app.capture_command = Mock(return_value=self.connections("telar-fabulas-dev", "telar-fabulas-dev-root"))
        self.assertTrue(await self.app.ensure_machine_connections())
        self.app.execute_command.assert_not_awaited()
        self.app.capture_command.assert_called_once()

    async def test_only_missing_member_of_pair_is_registered(self):
        for existing, missing in (("telar-fabulas-dev", "telar-fabulas-dev-root"),
                                  ("telar-fabulas-dev-root", "telar-fabulas-dev")):
            with self.subTest(existing=existing):
                self.app.execute_command.reset_mock()
                self.app.capture_command = Mock(side_effect=[self.connections(existing), self.inspect()])
                self.assertTrue(await self.app.ensure_machine_connections())
                self.app.execute_command.assert_awaited_once()
                command = self.app.execute_command.await_args.args[1]
                self.assertEqual(command[-2], missing)
                self.assertNotIn("--default", command)

    async def test_unknown_uid_never_guesses_socket_or_registers_partial_pair(self):
        self.config.write_text('{"Name": "telar-fabulas-dev", "HostUser": {}}', encoding="utf-8")
        self.app.capture_command = Mock(side_effect=[self.connections(), self.inspect()])
        self.assertFalse(await self.app.ensure_machine_connections())
        self.app.execute_command.assert_not_awaited()

    async def test_missing_identity_does_not_register_connection(self):
        self.identity.unlink()
        self.app.capture_command = Mock(side_effect=[self.connections(), self.inspect()])
        self.assertFalse(await self.app.ensure_machine_connections())
        self.app.execute_command.assert_not_awaited()

    async def test_connection_list_errors_never_trigger_registration(self):
        for result in ((125, "access denied"), (0, "not json"), (0, "{}")):
            with self.subTest(result=result):
                self.app.capture_command = Mock(return_value=result)
                self.assertFalse(await self.app.ensure_machine_connections())
                self.app.execute_command.assert_not_awaited()

    async def test_failed_registration_prevents_start_and_success_message(self):
        self.app.capture_command = Mock(side_effect=[
            (0, json.dumps([{"Name": "telar-fabulas-dev", "Running": False, "VMType": "wsl"}])),
            self.connections(), self.inspect(),
        ])
        self.app.execute_command.return_value = 125
        await self.app.start_podman()
        self.app.execute_command.assert_awaited_once()
        self.assertEqual(self.app.execute_command.await_args.args[1][1:4], ["system", "connection", "add"])
        self.assertFalse(any("listos" in call.args[0] for call in self.app.write_log.call_args_list))
        self.app.set_busy.assert_called_with(False)


class ProjectActionsTests(unittest.IsolatedAsyncioTestCase):
    async def test_every_compose_action_uses_the_project_connection(self):
        app = tui.ControlSistemaApp()
        app.capture_command = Mock(return_value=(0, '[{"State": "running"}]'))
        app.execute_command = AsyncMock(return_value=0)
        app.close_controlled_browser = AsyncMock()
        with patch.object(tui, "PODMAN_MACHINE", "telar-fabulas-dev"):
            async with app.run_test(size=(140, 36)):
                await app.build_app()
                await app.turn_on()
                await app.turn_off()
                commands = [call.args[1] for call in app.execute_command.await_args_list]
                self.assertEqual(commands, [
                    ["podman", "--connection", "telar-fabulas-dev", "compose", "build"],
                    ["podman", "--connection", "telar-fabulas-dev", "compose", "up", "-d"],
                    ["podman", "--connection", "telar-fabulas-dev", "compose", "stop"],
                ])
                for call in app.capture_command.call_args_list:
                    self.assertEqual(call.args[0],
                                     ["podman", "--connection", "telar-fabulas-dev", "ps",
                                      "--filter", "label=com.docker.compose.project=telar-fabulas",
                                      "--filter", "label=com.docker.compose.service=web", "--format", "json"])
                self.assertTrue(all(not button.disabled for button in app.query(tui.Button)))


class PodmanDiscoveryTests(unittest.TestCase):
    def test_windows_reinstall_is_found_with_stale_path(self):
        with (patch.dict(tui.os.environ, {"TELAR_PODMAN_PATH": "", "LOCALAPPDATA": "C:/Local"}),
              patch.object(tui.shutil, "which", return_value=None),
              patch.object(tui.platform, "system", return_value="Windows"),
              patch.object(tui.Path, "is_file", autospec=True,
                           side_effect=lambda path: path == tui.Path("C:/Local/Programs/Podman/podman.exe"))):
            self.assertEqual(tui.resolve_command(["podman", "machine", "list"]),
                             [str(tui.Path("C:/Local/Programs/Podman/podman.exe")), "machine", "list"])


class ComposeTransportTests(unittest.TestCase):
    def test_recovered_connection_uses_machine_pipe_not_interactive_ssh(self):
        machine = {"Name": "telar-fabulas-dev", "Rootful": False,
                   "ConnectionInfo": {"PodmanPipe": {"Path": r"\\.\pipe\podman-telar-fabulas-dev"}}}
        with (patch.object(tui, "PODMAN_MACHINE", "telar-fabulas-dev"),
              patch.object(tui.platform, "system", return_value="Windows"),
              patch.object(tui.ControlSistemaApp, "capture_command", return_value=(0, json.dumps([machine]))),
              patch.dict(os.environ, {"DOCKER_HOST": "ssh://wrong-host", "DOCKER_CONTEXT": "wrong-context",
                                      "DOCKER_TLS_VERIFY": "1"})):
            environment = tui.command_environment(tui.project_podman_command("compose", "ps"))
            self.assertEqual(environment["DOCKER_HOST"], "npipe:////./pipe/podman-telar-fabulas-dev")
            self.assertNotIn("DOCKER_CONTEXT", environment)
            self.assertNotIn("DOCKER_TLS_VERIFY", environment)
            self.assertEqual(os.environ["DOCKER_HOST"], "ssh://wrong-host")
            self.assertEqual(os.environ["DOCKER_CONTEXT"], "wrong-context")

    def test_failed_inspection_never_falls_back_to_global_docker_host(self):
        with (patch.object(tui.platform, "system", return_value="Windows"),
              patch.object(tui.ControlSistemaApp, "capture_command", return_value=(125, "machine not found"))):
            with self.assertRaises(ValueError):
                tui.command_environment(tui.project_podman_command("compose", "up", "-d"))

    def test_stale_socket_cleanup_preserves_other_machines_and_running_machine(self):
        with tempfile.TemporaryDirectory() as directory:
            podman_dir = Path(directory) / "podman"
            podman_dir.mkdir()
            target = podman_dir / "telar-fabulas-dev-api.sock"
            other = podman_dir / "podman-machine-default-api.sock"
            target.touch()
            other.touch()
            machine = {"Name": "telar-fabulas-dev", "State": "running",
                       "ConnectionInfo": {"PodmanSocket": {"Path": str(target)}}}
            with (patch.object(tui, "PODMAN_MACHINE", "telar-fabulas-dev"),
                  patch.object(tui.tempfile, "gettempdir", return_value=directory)):
                with self.assertRaises(ValueError):
                    tui.remove_stale_machine_socket(machine)
                self.assertTrue(target.exists())
                machine["State"] = "stopped"
                machine["ConnectionInfo"]["PodmanSocket"]["Path"] = str(other)
                with self.assertRaises(ValueError):
                    tui.remove_stale_machine_socket(machine)
                machine["ConnectionInfo"]["PodmanSocket"]["Path"] = str(target)
                tui.remove_stale_machine_socket(machine)
                self.assertFalse(target.exists())
                self.assertTrue(other.exists())


class BackgroundCommandTests(unittest.IsolatedAsyncioTestCase):
    async def test_close_button_remains_responsive_during_long_action(self):
        app = tui.ControlSistemaApp()
        app.refresh_status = AsyncMock()
        started = asyncio.Event()
        cancelled = asyncio.Event()

        async def long_command(*args):
            started.set()
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                cancelled.set()
                raise

        app.execute_command = long_command
        async with app.run_test(size=(140, 36)) as pilot:
            await pilot.click("#build_app")
            await asyncio.wait_for(started.wait(), timeout=2)
            self.assertFalse(app.query_one("#close_tui", tui.Button).disabled)
            await pilot.click("#close_tui")
        self.assertTrue(cancelled.is_set())

    async def test_streaming_command_timeout_kills_process(self):
        app = tui.ControlSistemaApp()
        app.write_log = Mock()
        with patch.object(tui, "COMMAND_TIMEOUT", 0.2):
            code = await app.execute_command("test", [sys.executable, "-c", "import time; time.sleep(60)"])
        self.assertEqual(code, 124)
        self.assertIn("tiempo de espera", app.write_log.call_args.args[0])


class CapturedCommandTests(unittest.TestCase):
    def test_background_commands_cannot_read_console_input(self):
        code, output = tui.ControlSistemaApp.capture_command([
            sys.executable, "-c", "import sys; print(repr(sys.stdin.read()))",
        ])
        self.assertEqual(code, 0)
        self.assertEqual(output.strip(), "''")

    def test_timeout_cleans_up_child_holding_output_pipe(self):
        script = (
            "import subprocess, sys, time; "
            "subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)']); "
            "time.sleep(60)"
        )
        with patch.object(tui, "STATUS_TIMEOUT", 1):
            code, output = tui.ControlSistemaApp.capture_command([sys.executable, "-c", script])
        self.assertEqual(code, 124)
        self.assertIn("1 segundos", output)


if __name__ == "__main__":
    unittest.main()
