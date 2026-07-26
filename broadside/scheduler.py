"""Schedule installer for Broadside — launchd, systemd, cron."""

from __future__ import annotations

import os
import platform
import shutil
import subprocess
import sys
from pathlib import Path

import click


LAUNCHD_PLIST = """\
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.broadside.weekly</string>
    <key>ProgramArguments</key>
    <array>
        <string>{broadside_path}</string>
        <string>run</string>
        <string>--yes</string>
    </array>
    <key>WorkingDirectory</key>
    <string>{working_dir}</string>
    <key>StartCalendarInterval</key>
    <dict>
        <key>Weekday</key>
        <integer>0</integer>
        <key>Hour</key>
        <integer>21</integer>
        <key>Minute</key>
        <integer>0</integer>
    </dict>
    <key>StandardOutPath</key>
    <string>{log_dir}/broadside.log</string>
    <key>StandardErrorPath</key>
    <string>{log_dir}/broadside-error.log</string>
    <key>EnvironmentVariables</key>
    <dict>
        <key>PATH</key>
        <string>/usr/local/bin:/usr/bin:/bin:{extra_path}</string>
    </dict>
</dict>
</plist>
"""

SYSTEMD_SERVICE = """\
[Unit]
Description=Broadside weekly video production run
After=network.target

[Service]
Type=oneshot
WorkingDirectory={working_dir}
ExecStart={broadside_path} run --yes
StandardOutput=append:{log_dir}/broadside.log
StandardError=append:{log_dir}/broadside-error.log
"""

SYSTEMD_TIMER = """\
[Unit]
Description=Broadside weekly timer

[Timer]
OnCalendar=Sun *-*-* 21:00:00
Persistent=true

[Install]
WantedBy=timers.target
"""


def install_schedule() -> None:
    broadside_path = shutil.which("broadside") or sys.executable + " -m broadside"
    working_dir = os.getcwd()
    log_dir = str(Path.home() / ".broadside" / "logs")
    Path(log_dir).mkdir(parents=True, exist_ok=True)

    system = platform.system()

    if system == "Darwin":
        _install_launchd(broadside_path, working_dir, log_dir)
    elif system == "Linux":
        _install_systemd(broadside_path, working_dir, log_dir)
    else:
        _install_cron(broadside_path, working_dir, log_dir)


def _install_launchd(broadside_path: str, working_dir: str, log_dir: str) -> None:
    extra_path = str(Path(sys.executable).parent)
    plist_content = LAUNCHD_PLIST.format(
        broadside_path=broadside_path,
        working_dir=working_dir,
        log_dir=log_dir,
        extra_path=extra_path,
    )

    plist_dir = Path.home() / "Library" / "LaunchAgents"
    plist_dir.mkdir(parents=True, exist_ok=True)
    plist_path = plist_dir / "com.broadside.weekly.plist"

    plist_path.write_text(plist_content)
    click.echo(f"Wrote launchd plist: {plist_path}")

    # Unload if already loaded, then load
    subprocess.run(
        ["launchctl", "unload", str(plist_path)],
        capture_output=True,
    )
    result = subprocess.run(
        ["launchctl", "load", str(plist_path)],
        capture_output=True,
        text=True,
    )
    if result.returncode == 0:
        click.echo("Schedule installed: Sunday 9pm weekly run")
        click.echo(f"Logs: {log_dir}/broadside.log")
    else:
        click.echo(f"launchctl load failed: {result.stderr}")


def _install_systemd(broadside_path: str, working_dir: str, log_dir: str) -> None:
    user_dir = Path.home() / ".config" / "systemd" / "user"
    user_dir.mkdir(parents=True, exist_ok=True)

    service_path = user_dir / "broadside.service"
    timer_path = user_dir / "broadside.timer"

    service_path.write_text(
        SYSTEMD_SERVICE.format(
            broadside_path=broadside_path,
            working_dir=working_dir,
            log_dir=log_dir,
        )
    )
    timer_path.write_text(SYSTEMD_TIMER)

    click.echo(f"Wrote systemd service: {service_path}")
    click.echo(f"Wrote systemd timer: {timer_path}")

    subprocess.run(["systemctl", "--user", "daemon-reload"], check=True)
    subprocess.run(["systemctl", "--user", "enable", "--now", "broadside.timer"], check=True)
    click.echo("Schedule installed: Sunday 9pm weekly run")


def _install_cron(broadside_path: str, working_dir: str, log_dir: str) -> None:
    cron_line = (
        f"0 21 * * 0 cd {working_dir} && {broadside_path} run --yes "
        f">> {log_dir}/broadside.log 2>&1"
    )

    click.echo("Add this line to your crontab (crontab -e):\n")
    click.echo(f"  {cron_line}")
    click.echo(f"\nLogs will go to: {log_dir}/broadside.log")
