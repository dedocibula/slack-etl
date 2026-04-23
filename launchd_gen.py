"""Generate the launchd .plist for daily scheduling and print install instructions."""

import os
import shutil
import sys
import textwrap

LABEL = "com.slack-etl.daily"
HOUR = 3
MINUTE = 0

project_dir = os.path.abspath(os.path.dirname(__file__))
uv_bin = shutil.which("uv") or "/usr/local/bin/uv"
plist_dest = os.path.expanduser(f"~/Library/LaunchAgents/{LABEL}.plist")

plist = textwrap.dedent(f"""\
    <?xml version="1.0" encoding="UTF-8"?>
    <!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
        "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
    <plist version="1.0">
    <dict>
        <key>Label</key>
        <string>{LABEL}</string>
        <key>ProgramArguments</key>
        <array>
            <string>{uv_bin}</string>
            <string>run</string>
            <string>python</string>
            <string>main.py</string>
        </array>
        <key>WorkingDirectory</key>
        <string>{project_dir}</string>
        <key>StartCalendarInterval</key>
        <dict>
            <key>Hour</key>
            <integer>{HOUR}</integer>
            <key>Minute</key>
            <integer>{MINUTE}</integer>
        </dict>
        <key>StandardOutPath</key>
        <string>{project_dir}/logs/launchd.out</string>
        <key>StandardErrorPath</key>
        <string>{project_dir}/logs/launchd.err</string>
        <key>RunAtLoad</key>
        <false/>
    </dict>
    </plist>
""")

print(plist)

print(
    f"# Install (run once):\n"
    f"#   uv run python launchd_gen.py > {plist_dest}\n"
    f"#   launchctl load {plist_dest}\n"
    f"#\n"
    f"# To unload:  launchctl unload {plist_dest}\n"
    f"# To reload:  launchctl unload {plist_dest} && launchctl load {plist_dest}",
    file=sys.stderr,
)
