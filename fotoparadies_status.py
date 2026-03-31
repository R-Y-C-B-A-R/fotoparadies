#!/usr/bin/env python3
"""
Check order status on fotoparadies.de
Usage:
  python3 fotoparadies_status.py <orderid>
  python3 fotoparadies_status.py -f orders.txt
  python3 fotoparadies_status.py -f orders.txt --email you@example.com

SMTP config file: ~/.fotoparadies.conf (INI format)
  [smtp]
  host     = mail.example.com
  port     = 587
  user     = user@example.com
  password = secret
  from     = fotoparadies@localhost
  starttls = true

State is stored in ~/.fotoparadies_state.json
"""

import configparser
import json
import re
import smtplib
import sys
import time
from datetime import datetime
from email.mime.text import MIMEText
from pathlib import Path
from typing import Dict, List, Optional, Tuple

STATE_FILE = Path.home() / ".fotoparadies_state.json"
CONFIG_FILE = Path.home() / ".fotoparadies.conf"


def load_state() -> dict:
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text())
        except (json.JSONDecodeError, OSError):
            return {}
    return {}


def save_state(state: dict) -> None:
    STATE_FILE.write_text(json.dumps(state, indent=2, ensure_ascii=False))


def fetch_order_status(page, order_id: str) -> Optional[Dict]:
    """Fetch status and return as dict, or None on error."""
    from playwright.sync_api import TimeoutError as PlaywrightTimeoutError

    url = f"https://www.fotoparadies.de/service/auftragsstatus.html#/?orderid={order_id}"

    try:
        page.goto(url, wait_until="networkidle", timeout=30000)
        page.wait_for_selector("cw-order-timeline", timeout=15000)
    except PlaywrightTimeoutError:
        print(f"Bestellung: {order_id}")
        print("  Fehler: Seite nicht geladen oder Bestellung nicht gefunden.")
        return None

    date_elem = page.query_selector("cw-order-timeline p.padding:not(.padding-top)")
    date_text = date_elem.inner_text().strip() if date_elem else ""

    updated_elem = page.query_selector("cw-order-timeline p.padding.padding-top")
    updated_text = updated_elem.inner_text().strip() if updated_elem else ""

    states = page.query_selector_all("cw-order-timeline .state")
    timeline = []
    for state in states:
        text_elem = state.query_selector("p.text")
        text = text_elem.inner_text().strip() if text_elem else ""
        img = state.query_selector("img")
        img_src = img.get_attribute("src") if img else ""

        if "_active.png" in img_src and "_inactive" not in img_src:
            marker = ">>> AKTUELL"
        elif "_future.png" in img_src:
            marker = "  [ offen ]"
        else:
            marker = "  [  ok   ]"

        timeline.append({"marker": marker, "text": text})

    return {
        "order_id": order_id,
        "date": date_text,
        "updated": updated_text,
        "timeline": timeline,
    }


def print_status(data: dict) -> None:
    print(f"Bestellung: {data['order_id']}")
    if data["date"]:
        print(data["date"])
    print()
    print("Status:")
    for step in data["timeline"]:
        print(f"  {step['marker']}  {step['text']}")
    print()
    if data["updated"]:
        print(data["updated"])


def find_active_step(data: dict) -> str:
    for step in data["timeline"]:
        if "AKTUELL" in step["marker"]:
            return step["text"]
    return ""


def load_smtp_config() -> dict:
    cfg = configparser.ConfigParser()
    if not CONFIG_FILE.exists():
        print(f"Error: Config file not found: {CONFIG_FILE}", file=sys.stderr)
        print(f"Create it with:", file=sys.stderr)
        print(f"  [smtp]", file=sys.stderr)
        print(f"  host     = mail.example.com", file=sys.stderr)
        print(f"  port     = 587", file=sys.stderr)
        print(f"  user     = user@example.com", file=sys.stderr)
        print(f"  password = secret", file=sys.stderr)
        print(f"  from     = fotoparadies@localhost", file=sys.stderr)
        print(f"  starttls = true", file=sys.stderr)
        sys.exit(1)
    cfg.read(CONFIG_FILE)
    section = cfg["smtp"] if "smtp" in cfg else {}
    return {
        "host":      section.get("host", "localhost"),
        "port":      int(section.get("port", "25")),
        "user":      section.get("user", ""),
        "password":  section.get("password", ""),
        "from":      section.get("from", "fotoparadies@localhost"),
        "starttls":  section.get("starttls", "false").lower() in ("1", "true", "yes"),
    }


def send_email(recipient: str, order_id: str, old_step: str, new_step: str, data: dict) -> None:
    cfg = load_smtp_config()
    smtp_host = cfg["host"]
    smtp_port = cfg["port"]
    smtp_user = cfg["user"]
    smtp_password = cfg["password"]
    smtp_from = cfg["from"]
    use_starttls = cfg["starttls"]

    subject = f"Fotoparadies Status-Änderung: {order_id}"

    lines = [
        f"Die Bestellung {order_id} hat einen neuen Status.",
        "",
        f"Vorher: {old_step or '(unbekannt)'}",
        f"Jetzt:  {new_step}",
        "",
        "Aktueller Stand:",
    ]
    for step in data["timeline"]:
        lines.append(f"  {step['marker']}  {step['text']}")
    if data["date"]:
        lines.insert(1, data["date"])
    if data["updated"]:
        lines.append("")
        lines.append(data["updated"])

    body = "\n".join(lines)
    msg = MIMEText(body, "plain", "utf-8")
    msg["Subject"] = subject
    msg["From"] = smtp_from
    msg["To"] = recipient

    try:
        with smtplib.SMTP(smtp_host, smtp_port) as smtp:
            if use_starttls:
                smtp.starttls()
            if smtp_user and smtp_password:
                smtp.login(smtp_user, smtp_password)
            smtp.sendmail(smtp_from, [recipient], msg.as_string())
        print(f"  -> E-Mail an {recipient} gesendet (Status: {new_step})")
    except Exception as e:
        print(f"  -> E-Mail-Fehler: {e}", file=sys.stderr)


def read_order_ids(filepath: str) -> List[str]:
    try:
        with open(filepath) as f:
            return [line.strip() for line in f if line.strip() and not line.startswith("#")]
    except FileNotFoundError:
        print(f"Error: File '{filepath}' not found.")
        sys.exit(1)


def run(order_ids: List[str], email_recipient: Optional[str] = None) -> None:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("playwright is not installed. Run:")
        print("  pip3 install playwright && python3 -m playwright install chromium")
        sys.exit(1)

    state = load_state() if email_recipient else {}
    state_changed = False

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        separator = "=" * 50
        for i, order_id in enumerate(order_ids):
            if i > 0:
                print(separator)
            data = fetch_order_status(page, order_id)
            if data is None:
                continue
            print_status(data)

            if email_recipient:
                current_step = find_active_step(data)
                previous_step = state.get(order_id, {}).get("active_step")
                if current_step != previous_step:
                    send_email(email_recipient, order_id, previous_step, current_step, data)
                    state[order_id] = {"active_step": current_step}
                    state_changed = True
        browser.close()

    if email_recipient and state_changed:
        save_state(state)


def parse_interval(value: str) -> int:
    """Parse interval string (e.g. 1h, 30m, 90s) into seconds."""
    m = re.fullmatch(r"(\d+)(s|m|h)", value)
    if not m:
        print(f"Error: Invalid interval '{value}'. Use e.g. 30m, 1h, 90s.")
        sys.exit(1)
    n, unit = int(m.group(1)), m.group(2)
    return n * {"s": 1, "m": 60, "h": 3600}[unit]


def parse_args(argv: List[str]) -> Tuple[List[str], Optional[str], Optional[int]]:
    """Returns (order_ids, email_recipient, loop_interval_seconds)."""
    args = argv[1:]
    email = None
    loop_seconds = None

    if "--email" in args:
        idx = args.index("--email")
        if idx + 1 >= len(args):
            print("Error: --email requires an address.")
            sys.exit(1)
        email = args[idx + 1]
        args = args[:idx] + args[idx + 2:]

    if "--loop" in args:
        idx = args.index("--loop")
        # optional interval after --loop
        if idx + 1 < len(args) and re.fullmatch(r"\d+[smh]", args[idx + 1]):
            loop_seconds = parse_interval(args[idx + 1])
            args = args[:idx] + args[idx + 2:]
        else:
            loop_seconds = 3600  # default: 1h
            args = args[:idx] + args[idx + 1:]

    if len(args) == 2 and args[0] == "-f":
        return read_order_ids(args[1]), email, loop_seconds
    elif len(args) == 1 and args[0] not in ("-h", "--help"):
        return [args[0]], email, loop_seconds
    else:
        print("Usage:")
        print(f"  {argv[0]} <orderid>")
        print(f"  {argv[0]} -f orders.txt")
        print(f"  {argv[0]} -f orders.txt --email you@example.com")
        print(f"  {argv[0]} -f orders.txt --email you@example.com --loop [interval]")
        print(f"  Interval examples: 30m, 1h, 2h  (default: 1h)")
        print()
        print(f"SMTP config: {CONFIG_FILE}")
        sys.exit(0 if args in (["-h"], ["--help"]) else 1)


if __name__ == "__main__":
    order_ids, email_recipient, loop_interval = parse_args(sys.argv)
    if not order_ids:
        print("Error: No order IDs found.")
        sys.exit(1)

    if loop_interval:
        print(f"Loop-Modus: Abfrage alle {loop_interval}s. Abbrechen mit Ctrl+C.")
        print()
        while True:
            print(f"[{datetime.now().strftime('%H:%M:%S')}] Prüfe Status...")
            run(order_ids, email_recipient)
            print(f"Nächste Prüfung in {loop_interval}s.")
            time.sleep(loop_interval)
    else:
        run(order_ids, email_recipient)
