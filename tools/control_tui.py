from __future__ import annotations

import argparse
import asyncio
import json
import os
import platform
import shutil
import signal
import subprocess
import tempfile
from datetime import datetime
from pathlib import Path
from urllib.parse import quote

from rich.markup import escape
from textual.app import App, ComposeResult
from textual.containers import Horizontal, Vertical
from textual.widgets import Button, Footer, Header, RichLog, Static


ROOT_DIR = Path(__file__).resolve().parents[1]
LOCAL_URL = os.getenv("TELAR_LOCAL_URL", "http://localhost:8000")
SYSTEM_NAME = os.getenv("TELAR_SYSTEM_NAME", "Telar de Fábulas")
APP_TITLE = f"Control del Sistema {SYSTEM_NAME}"
APP_SUBTITLE = "Podman Compose local"
CHROME_PROFILE = ROOT_DIR / ".tui" / "chrome-profile"
PODMAN_MACHINE = os.getenv("TELAR_PODMAN_MACHINE", "telar-fabulas-dev")
WSL_CONTAINERS_CONF_DIR = "/usr/share/containers/containers.conf.d"
STATUS_TIMEOUT = 20
COMMAND_TIMEOUT = 120
BUILD_TIMEOUT = 1800


def podman_executable() -> str | None:
    """Find Podman even when this terminal predates a Windows reinstall."""
    configured = os.getenv("TELAR_PODMAN_PATH")
    if configured:
        return configured
    executable = shutil.which("podman")
    if executable or platform.system().lower() != "windows":
        return executable
    candidates = [
        Path(os.getenv("LOCALAPPDATA", "")) / "Programs/Podman/podman.exe",
        Path(os.getenv("PROGRAMFILES", "C:/Program Files")) / "RedHat/Podman/podman.exe",
        Path(os.getenv("PROGRAMFILES", "C:/Program Files")) / "Podman/podman.exe",
    ]
    return next((str(path) for path in candidates if path.is_file()), None)


def resolve_command(command: list[str]) -> list[str]:
    if command[0] == "podman":
        return [podman_executable() or "podman", *command[1:]]
    return command


def project_podman_command(*arguments: str) -> list[str]:
    return ["podman", "--connection", PODMAN_MACHINE, *arguments]


def process_options() -> dict:
    # OpenSSH can read CONIN$ even when standard input is redirected. Give
    # background commands no console, as well as no interactive standard input.
    if platform.system().lower() == "windows":
        return {"stdin": subprocess.DEVNULL, "creationflags": subprocess.CREATE_NO_WINDOW}
    return {"stdin": subprocess.DEVNULL, "start_new_session": True}


def stop_process_tree(pid: int) -> None:
    if platform.system().lower() == "windows":
        subprocess.run(
            ["taskkill.exe", "/PID", str(pid), "/T", "/F"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            timeout=10, check=False, **process_options(),
        )
    else:
        try:
            os.killpg(pid, signal.SIGKILL)
        except ProcessLookupError:
            pass


def command_environment(command: list[str]) -> dict[str, str]:
    environment = os.environ.copy()
    if platform.system().lower() == "windows" and command[:4] == project_podman_command("compose"):
        code, output = ControlSistemaApp.capture_command(["podman", "machine", "inspect", PODMAN_MACHINE])
        if code != 0:
            raise ValueError(f"No se pudo consultar la conexión local de Compose: {output.strip()}")
        try:
            machine = json.loads(output)[0]
            if machine["Name"] != PODMAN_MACHINE or machine["Rootful"]:
                raise ValueError("La TUI requiere la máquina seleccionada en modo rootless.")
            pipe = machine["ConnectionInfo"]["PodmanPipe"]["Path"]
            if not isinstance(pipe, str) or not pipe.startswith("\\\\.\\pipe\\"):
                raise ValueError("Podman no devolvió una conexión local válida para Compose.")
        except (KeyError, TypeError, IndexError) as error:
            raise ValueError("Podman no devolvió la conexión local de Compose.") from error
        # Connections restored with `system connection add` have no IsMachine
        # marker. Otherwise Podman sends Docker Compose an SSH URL without its
        # identity, which prompts for a password. Pin only this child's endpoint.
        environment["DOCKER_HOST"] = "npipe://" + pipe.replace("\\", "/")
        for name in ("DOCKER_CONTEXT", "DOCKER_TLS_VERIFY", "DOCKER_CERT_PATH", "DOCKER_TLS"):
            environment.pop(name, None)
    return environment


def remove_stale_machine_socket(machine: dict) -> None:
    """Remove only this stopped machine's transient Windows API socket."""
    if machine["Name"] != PODMAN_MACHINE or machine["State"] != "stopped":
        raise ValueError("La máquina debe estar detenida para limpiar su socket temporal.")
    expected = Path(tempfile.gettempdir()) / "podman" / f"{PODMAN_MACHINE}-api.sock"
    actual = Path(machine["ConnectionInfo"]["PodmanSocket"]["Path"])
    if actual.resolve() != expected.resolve():
        raise ValueError("La ruta del socket temporal no corresponde a la máquina seleccionada.")
    actual.unlink(missing_ok=True)


def missing_connection_commands(machine: dict, existing_names: set[str]) -> list[list[str]]:
    """Recover only missing connection records from this machine's metadata."""
    if machine["Name"] != PODMAN_MACHINE:
        raise ValueError("La inspección corresponde a otra máquina.")
    ssh = machine["SSHConfig"]
    identity = ssh["IdentityPath"]
    username = ssh["RemoteUsername"]
    port = ssh["Port"]
    if not isinstance(identity, str) or not Path(identity).is_file():
        raise ValueError("No se encontró la clave SSH registrada para la máquina.")
    if not isinstance(username, str) or not username or type(port) is not int or not 1 <= port <= 65535:
        raise ValueError("La configuración SSH de la máquina no es válida.")

    commands = []
    if PODMAN_MACHINE not in existing_names:
        # Inspect exposes SSH details but not the guest UID. Read Podman's own
        # machine metadata instead of assuming UID 1000 or guessing a port.
        config_path = Path(machine["ConfigDir"]["Path"]) / f"{PODMAN_MACHINE}.json"
        config = json.loads(config_path.read_text(encoding="utf-8"))
        if config["Name"] != PODMAN_MACHINE:
            raise ValueError("La configuración corresponde a otra máquina.")
        uid = config["HostUser"]["UID"]
        if type(uid) is not int or uid < 0:
            raise ValueError("No se pudo determinar el UID del usuario de la máquina.")
        uri = f"ssh://{quote(username, safe='')}@127.0.0.1:{port}/run/user/{uid}/podman/podman.sock"
        commands.append(["podman", "system", "connection", "add", "--identity", identity,
                         PODMAN_MACHINE, uri])
    root_name = f"{PODMAN_MACHINE}-root"
    if root_name not in existing_names:
        commands.append(["podman", "system", "connection", "add", "--identity", identity,
                         root_name, f"ssh://root@127.0.0.1:{port}/run/podman/podman.sock"])
    return commands


def decode_output(data: bytes) -> str:
    return data.decode("utf-8", errors="replace").rstrip()


def quote_powershell(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


class ControlSistemaApp(App):
    CSS = """
    Screen {
        background: #0d1720;
        color: #eef5ff;
    }

    Header {
        background: #1f2a33;
        color: #d9e5ee;
    }

    Footer {
        background: #1f2a33;
        color: #f2efe7;
    }

    #root {
        height: 100%;
        background: #0d1720;
    }

    #hero {
        height: 4;
        content-align: center middle;
        background: #132236;
        text-style: bold;
        color: #ffffff;
    }

    #status {
        height: 2;
        content-align: center middle;
        background: #0d1720;
        color: #7ed957;
        border-bottom: solid #244257;
    }

    #main {
        height: 1fr;
    }

    #sidebar {
        width: 33;
        padding: 2 1 1 1;
        border-right: solid #244257;
        background: #0d1720;
    }

    #log_panel {
        width: 1fr;
        padding: 2 2 1 2;
        background: #0d1720;
    }

    #log_title {
        height: 2;
        text-style: bold;
        color: #ffffff;
    }

    Button {
        width: 100%;
        height: 3;
        margin-bottom: 1;
        text-style: bold;
        border: tall #213446;
    }

    #start_podman {
        background: #1688d8;
        color: #ffffff;
    }

    #build_app {
        background: #ffad32;
        color: #101418;
    }

    #turn_on {
        background: #51c878;
        color: #06130b;
    }

    #open_browser {
        background: #1688d8;
        color: #ffffff;
    }

    #turn_off {
        background: #bf3d63;
        color: #ffffff;
    }

    #close_tui {
        background: #263848;
        color: #ffffff;
    }

    #logs {
        height: 1fr;
        border: round #244257;
        background: #030b12;
        color: #edf4ff;
        padding: 1;
    }
    """

    TITLE = APP_TITLE
    SUB_TITLE = APP_SUBTITLE
    BINDINGS = [
        ("q", "quit", "Cerrar"),
        ("r", "refresh_status", "Actualizar estado"),
    ]

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        with Vertical(id="root"):
            yield Static(APP_TITLE, id="hero")
            yield Static("Estado: revisando...", id="status")
            with Horizontal(id="main"):
                with Vertical(id="sidebar"):
                    yield Button("Arrancar podman", id="start_podman")
                    yield Button("Construir aplicación", id="build_app")
                    yield Button("Encender", id="turn_on")
                    yield Button("Abrir navegador", id="open_browser")
                    yield Button("Apagar", id="turn_off")
                    yield Button("Cerrar", id="close_tui")
                with Vertical(id="log_panel"):
                    yield Static("Logs", id="log_title")
                    yield RichLog(id="logs", wrap=True, markup=True, highlight=True)
        yield Footer()

    async def on_mount(self) -> None:
        self.write_log("[bold yellow]TUI lista.[/]")
        self.write_log(f"Raíz del proyecto: {ROOT_DIR}")
        self.write_log(f"URL local: {LOCAL_URL}")
        self.write_log(f"Máquina y conexión de Podman: {escape(PODMAN_MACHINE)}")
        self.run_worker(self.refresh_status(), group="status", exclusive=True)

    @property
    def logs(self) -> RichLog:
        return self.query_one("#logs", RichLog)

    @property
    def status(self) -> Static:
        return self.query_one("#status", Static)

    def write_log(self, message: str, *, stamp: bool = True) -> None:
        if stamp:
            timestamp = datetime.now().strftime("%H:%M:%S")
            self.logs.write(f"[bold #7ed957]{timestamp}[/]  {message}")
        else:
            self.logs.write(message)

    def set_busy(self, busy: bool) -> None:
        for button in self.query(Button):
            button.disabled = busy and button.id != "close_tui"

    async def action_refresh_status(self) -> None:
        self.run_worker(self.refresh_status(), group="status", exclusive=True)

    async def on_button_pressed(self, event: Button.Pressed) -> None:
        actions = {
            "start_podman": self.start_podman,
            "build_app": self.build_app,
            "turn_on": self.turn_on,
            "open_browser": self.open_browser,
            "turn_off": self.turn_off,
            "close_tui": self.close_tui,
        }
        action = actions.get(event.button.id or "")
        if action is not None:
            if event.button.id == "close_tui":
                await action()
            else:
                self.run_worker(action(), group="commands", exclusive=True)

    async def start_podman(self) -> None:
        self.set_busy(True)
        try:
            code, output = await asyncio.to_thread(
                self.capture_command, ["podman", "machine", "list", "--format", "json"]
            )
            if code != 0:
                self.write_log(f"[red]No se pudo consultar Podman: {escape(output)}[/]")
                return
            try:
                machines = json.loads(output)
                machine = next(item for item in machines if item["Name"] == PODMAN_MACHINE)
            except StopIteration:
                self.write_log(
                    f"[red]No existe la máquina {escape(PODMAN_MACHINE)}. "
                    "Revisa la instalación; no se seleccionará otra máquina automáticamente.[/]"
                )
                return
            except (ValueError, KeyError, TypeError):
                self.write_log("[red]Podman devolvió una lista de máquinas no válida.[/]")
                return

            if machine.get("Starting"):
                self.write_log("[yellow]La máquina todavía está arrancando. Espera y vuelve a intentarlo.[/]")
                return
            if not await self.ensure_machine_connections():
                return
            if not machine.get("Running"):
                if platform.system().lower() == "windows":
                    code, output = await asyncio.to_thread(
                        self.capture_command, ["podman", "machine", "inspect", PODMAN_MACHINE]
                    )
                    if code != 0:
                        self.write_log(f"[red]No se pudo inspeccionar la máquina: {escape(output)}[/]")
                        return
                    try:
                        remove_stale_machine_socket(json.loads(output)[0])
                    except (OSError, ValueError, KeyError, TypeError, IndexError) as error:
                        self.write_log(f"[red]No se pudo preparar el socket local: {escape(str(error))}[/]")
                        return
                if platform.system().lower() == "windows" and machine.get("VMType") == "wsl":
                    # Podman 6.1.4 writes its cgroupfs config here without creating
                    # the directory on machines retained from an older installation.
                    distro = PODMAN_MACHINE if PODMAN_MACHINE.startswith("podman-") else f"podman-{PODMAN_MACHINE}"
                    code = await self.execute_command(
                        "Preparar configuración de Podman en WSL",
                        ["wsl.exe", "--distribution", distro, "--user", "root", "--exec",
                         "mkdir", "-p", WSL_CONTAINERS_CONF_DIR],
                    )
                    if code != 0:
                        return
                code = await self.execute_command(
                    "Arrancar podman",
                    ["podman", "machine", "start", "--update-connection=false", PODMAN_MACHINE],
                )
                if code != 0:
                    return

            code, output = await asyncio.to_thread(
                self.capture_command, project_podman_command("info", "--format", "{{.Host.Hostname}}")
            )
            if code == 0:
                code, output = await asyncio.to_thread(
                    self.capture_command, project_podman_command("compose", "ps")
                )
                if code == 0:
                    self.write_log(f"[green]Podman y Compose listos en {escape(PODMAN_MACHINE)}.[/]")
                else:
                    self.write_log(
                        "[red]Podman responde, pero Compose no está disponible. "
                        f"Revisa el puente local de la máquina: {escape(output)}[/]"
                    )
            else:
                self.write_log(f"[red]La máquina está iniciada, pero su conexión no responde: {escape(output)}[/]")
        finally:
            self.set_busy(False)
            await self.refresh_status()

    async def ensure_machine_connections(self) -> bool:
        code, output = await asyncio.to_thread(
            self.capture_command, ["podman", "system", "connection", "list", "--format", "json"]
        )
        if code != 0:
            self.write_log(f"[red]No se pudieron consultar las conexiones: {escape(output)}[/]")
            return False
        try:
            connections = json.loads(output)
            if not isinstance(connections, list):
                raise ValueError("Se esperaba una lista de conexiones.")
            names = {connection["Name"] for connection in connections}
        except (ValueError, KeyError, TypeError):
            self.write_log("[red]Podman devolvió una lista de conexiones no válida.[/]")
            return False
        if {PODMAN_MACHINE, f"{PODMAN_MACHINE}-root"} <= names:
            return True

        code, output = await asyncio.to_thread(
            self.capture_command, ["podman", "machine", "inspect", PODMAN_MACHINE]
        )
        if code != 0:
            self.write_log(f"[red]No se pudo inspeccionar la máquina para recuperar su conexión: {escape(output)}[/]")
            return False
        try:
            commands = missing_connection_commands(json.loads(output)[0], names)
        except (OSError, ValueError, KeyError, TypeError, IndexError) as error:
            self.write_log(f"[red]No se pudo recuperar la configuración de conexión: {escape(str(error))}[/]")
            return False
        for command in commands:
            name = command[-2]
            self.write_log(f"[yellow]Falta la conexión {escape(name)}; se registrará con los datos de la máquina.[/]")
            code = await self.execute_command(f"Registrar conexión {name}", command)
            if code != 0:
                return False
        return True

    async def build_app(self) -> None:
        await self.run_command("Construir aplicación", project_podman_command("compose", "build"))

    async def turn_on(self) -> None:
        await self.run_command("Encender", project_podman_command("compose", "up", "-d"))

    async def turn_off(self) -> None:
        await self.close_controlled_browser()
        await self.run_command("Apagar servicios", project_podman_command("compose", "stop"))

    async def close_tui(self) -> None:
        self.workers.cancel_group(self, "commands")
        self.workers.cancel_group(self, "status")
        self.exit()

    async def run_command(self, label: str, command: list[str]) -> None:
        self.set_busy(True)
        try:
            await self.execute_command(label, command)
        finally:
            self.set_busy(False)
            await self.refresh_status()

    async def execute_command(self, label: str, command: list[str]) -> int:
        self.write_log("")
        self.write_log(f"[bold cyan]{label}[/]")
        self.write_log(f"[dim]$ {escape(subprocess.list2cmdline(command))}[/]")
        try:
            environment = await asyncio.to_thread(command_environment, command)
            process = await asyncio.create_subprocess_exec(
                *resolve_command(command),
                cwd=ROOT_DIR,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
                env=environment,
                **process_options(),
            )
        except FileNotFoundError:
            self.write_log(f"[red]No se encontró el comando: {command[0]}[/]")
            return 127
        except (OSError, ValueError) as error:
            self.write_log(f"[red]No se pudo ejecutar el comando: {escape(str(error))}[/]")
            return 126

        try:
            timeout = BUILD_TIMEOUT if command[:4] == project_podman_command("compose") and command[4:5] in (["build"], ["up"]) else COMMAND_TIMEOUT
            async with asyncio.timeout(timeout):
                assert process.stdout is not None
                while True:
                    line = await process.stdout.readline()
                    if not line:
                        break
                    self.write_log(escape(decode_output(line)))
                code = await process.wait()
        except (TimeoutError, asyncio.CancelledError) as error:
            await asyncio.to_thread(stop_process_tree, process.pid)
            if process.returncode is None:
                process.kill()
            await process.wait()
            if isinstance(error, asyncio.CancelledError):
                raise
            self.write_log("[red]El comando excedió el tiempo de espera; se detuvieron sus procesos.[/]")
            return 124
        if code == 0:
            self.write_log("[green]Comando completado.[/]")
        else:
            self.write_log(f"[red]Comando terminado con código {code}.[/]")
        return code

    async def refresh_status(self) -> None:
        self.status.update("[bold yellow]Estado: revisando...[/]")
        code, output = await asyncio.to_thread(
            self.capture_command,
            project_podman_command("ps", "--filter", "label=com.docker.compose.project=telar-fabulas",
                                   "--filter", "label=com.docker.compose.service=web", "--format", "json"),
        )
        if code != 0:
            self.status.update("[bold red]Estado: sin conexión con Podman[/]")
            return
        try:
            containers = json.loads(output)
            running = any(container.get("State") == "running" for container in containers)
        except (ValueError, TypeError, AttributeError):
            self.status.update("[bold red]Estado: respuesta de Podman no válida[/]")
            return
        if running:
            self.status.update("[bold green]Estado: encendido[/]")
        else:
            self.status.update("[bold red]Estado: apagado[/]")

    @staticmethod
    def capture_command(command: list[str]) -> tuple[int, str]:
        try:
            process = subprocess.Popen(
                resolve_command(command),
                cwd=ROOT_DIR,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                errors="replace",
                env=command_environment(command),
                **process_options(),
            )
            try:
                stdout, stderr = process.communicate(timeout=STATUS_TIMEOUT)
            except subprocess.TimeoutExpired:
                stop_process_tree(process.pid)
                if process.poll() is None:
                    process.kill()
                process.communicate(timeout=5)
                return 124, f"El comando no respondió en {STATUS_TIMEOUT} segundos."
        except FileNotFoundError:
            return 127, f"No se encontró el comando: {command[0]}"
        except (OSError, ValueError, subprocess.TimeoutExpired) as error:
            return 126, str(error)
        return process.returncode, stdout + stderr

    async def open_browser(self) -> None:
        self.write_log("")
        self.write_log("[bold cyan]Abrir navegador[/]")
        command = self.browser_command()
        if command is None:
            self.write_log("[red]No encontré Google Chrome. Configura TELAR_CHROME_PATH si está en otra ruta.[/]")
            return

        CHROME_PROFILE.mkdir(parents=True, exist_ok=True)
        self.write_log(f"[dim]Perfil controlado de Chrome: {CHROME_PROFILE}[/]")
        await asyncio.to_thread(
            subprocess.Popen,
            command,
            cwd=ROOT_DIR,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        self.write_log(f"[green]Navegador abierto en {LOCAL_URL}[/]")

    @staticmethod
    def browser_command() -> list[str] | None:
        chrome_from_env = os.getenv("TELAR_CHROME_PATH")
        candidates = [
            shutil.which("chrome"),
            shutil.which("chrome.exe"),
            shutil.which("google-chrome"),
            shutil.which("google-chrome-stable"),
            chrome_from_env,
            r"C:\Program Files\Google\Chrome\Application\chrome.exe",
            r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
        ]
        chrome = next((Path(candidate) for candidate in candidates if candidate and Path(candidate).exists()), None)
        if chrome is None:
            return None
        return [
            str(chrome),
            f"--user-data-dir={CHROME_PROFILE}",
            "--new-window",
            f"--app={LOCAL_URL}",
        ]

    async def close_controlled_browser(self) -> None:
        self.write_log("")
        self.write_log("[bold cyan]Apagar navegador[/]")
        if platform.system().lower() != "windows":
            self.write_log("[yellow]Cierre automático de navegador disponible solo en Windows.[/]")
            return

        powershell = shutil.which("powershell") or shutil.which("pwsh")
        if powershell is None:
            self.write_log("[yellow]No encontré PowerShell para cerrar la ventana controlada.[/]")
            return

        profile = quote_powershell(str(CHROME_PROFILE))
        script = (
            f"$profile = {profile}; "
            "Get-CimInstance Win32_Process | "
            "Where-Object { $_.CommandLine -and $_.CommandLine.Contains($profile) } | "
            "ForEach-Object { Stop-Process -Id $_.ProcessId -Force }"
        )
        code, output = await asyncio.to_thread(
            self.capture_command,
            [powershell, "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", script],
        )
        if output.strip():
            self.write_log(output.strip())
        if code == 0:
            self.write_log("[green]Navegador controlado apagado.[/]")
        else:
            self.write_log(f"[yellow]No se pudo confirmar el cierre del navegador. Código {code}.[/]")


async def render_smoke_test() -> None:
    class SmokeTestApp(ControlSistemaApp):
        async def refresh_status(self) -> None:
            self.status.update("Estado: prueba de interfaz")

    app = SmokeTestApp()
    async with app.run_test(size=(140, 36)) as pilot:
        await pilot.pause()
        assert app.query_one("#hero", Static)
        assert app.query_one("#status", Static)
        assert len(app.query(Button)) == 6
        assert app.query_one("#logs", RichLog)


def smoke_test() -> int:
    missing = [] if podman_executable() else ["podman"]
    asyncio.run(render_smoke_test())
    print(f"SMOKE_TEST_OK title={APP_TITLE}")
    print(f"project_root={ROOT_DIR}")
    print(f"local_url={LOCAL_URL}")
    print(f"podman_machine={PODMAN_MACHINE}")
    if missing:
        print("missing_commands=" + ",".join(missing))
        return 1
    return 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="TUI de control para Telar de Fábulas.")
    parser.add_argument("--smoke-test", action="store_true", help="Importa la TUI y valida comandos mínimos.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.smoke_test:
        return smoke_test()
    ControlSistemaApp().run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
