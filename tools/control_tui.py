from __future__ import annotations

import argparse
import asyncio
import os
import platform
import shutil
import subprocess
from datetime import datetime
from pathlib import Path

from textual.app import App, ComposeResult
from textual.containers import Horizontal, Vertical
from textual.widgets import Button, Footer, Header, RichLog, Static


ROOT_DIR = Path(__file__).resolve().parents[1]
LOCAL_URL = os.getenv("TELAR_LOCAL_URL", "http://localhost:8000")
SYSTEM_NAME = os.getenv("TELAR_SYSTEM_NAME", "Telar de Fábulas")
APP_TITLE = f"Control del Sistema {SYSTEM_NAME}"
APP_SUBTITLE = "Podman Compose local"
CHROME_PROFILE = ROOT_DIR / ".tui" / "chrome-profile"


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
        await self.refresh_status()

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
        await self.refresh_status()

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
            await action()

    async def start_podman(self) -> None:
        await self.run_command("Arrancar podman", ["podman", "machine", "start"])

    async def build_app(self) -> None:
        await self.run_command("Construir aplicación", ["podman", "compose", "build"])

    async def turn_on(self) -> None:
        await self.run_command("Encender", ["podman", "compose", "up", "-d"])

    async def turn_off(self) -> None:
        await self.close_controlled_browser()
        await self.run_command("Apagar servicios", ["podman", "compose", "stop"])

    async def close_tui(self) -> None:
        self.exit()

    async def run_command(self, label: str, command: list[str]) -> None:
        self.set_busy(True)
        self.write_log("")
        self.write_log(f"[bold cyan]{label}[/]")
        self.write_log(f"[dim]$ {' '.join(command)}[/]")
        try:
            process = await asyncio.create_subprocess_exec(
                *command,
                cwd=ROOT_DIR,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
            )
        except FileNotFoundError:
            self.write_log(f"[red]No se encontró el comando: {command[0]}[/]")
            self.set_busy(False)
            await self.refresh_status()
            return

        assert process.stdout is not None
        while True:
            line = await process.stdout.readline()
            if not line:
                break
            self.write_log(decode_output(line))

        code = await process.wait()
        if code == 0:
            self.write_log("[green]Comando completado.[/]")
        else:
            self.write_log(f"[red]Comando terminado con código {code}.[/]")
        await self.refresh_status()
        self.set_busy(False)

    async def refresh_status(self) -> None:
        self.status.update("[bold yellow]Estado: revisando...[/]")
        code, output = await asyncio.to_thread(self.capture_command, ["podman", "compose", "ps"])
        if code == 0 and "telar-fabulas-web-1" in output and "Up" in output:
            self.status.update("[bold green]Estado: encendido[/]")
        else:
            self.status.update("[bold red]Estado: apagado[/]")

    @staticmethod
    def capture_command(command: list[str]) -> tuple[int, str]:
        try:
            result = subprocess.run(
                command,
                cwd=ROOT_DIR,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                check=False,
            )
        except FileNotFoundError:
            return 127, ""
        return result.returncode, result.stdout + result.stderr

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
    app = ControlSistemaApp()
    async with app.run_test(size=(140, 36)) as pilot:
        await pilot.pause()
        assert app.query_one("#hero", Static)
        assert app.query_one("#status", Static)
        assert len(app.query(Button)) == 6
        assert app.query_one("#logs", RichLog)


def smoke_test() -> int:
    required = ["podman"]
    missing = [command for command in required if shutil.which(command) is None]
    asyncio.run(render_smoke_test())
    print(f"SMOKE_TEST_OK title={APP_TITLE}")
    print(f"project_root={ROOT_DIR}")
    print(f"local_url={LOCAL_URL}")
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
