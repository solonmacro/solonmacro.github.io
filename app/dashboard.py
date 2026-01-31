#!/usr/bin/env python3
import argparse
import json
import os
import sys
import yaml
from datetime import datetime

BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
APP_DIR = os.path.dirname(__file__)

def load_config():
    path = os.path.join(APP_DIR, "config.yaml")
    with open(path, "r") as f:
        return yaml.safe_load(f)

def ensure_dir(path):
    if not os.path.exists(path):
        os.makedirs(path)

def now_utc():
    return datetime.utcnow().isoformat(timespec="seconds") + "Z"

def determine_status(score, cfg):
    if score <= cfg["scoring"]["green_max"]:
        return "green"
    if score <= cfg["scoring"]["yellow_max"]:
        return "yellow"
    return "red"

def run_dashboard(mode):
    cfg = load_config()

    out_cfg = cfg["output"]
    data_dir = os.path.join(BASE_DIR, out_cfg["data_dir"])
    ensure_dir(data_dir)

    # -------------------------
    # PLACEHOLDER LOGIC
    # -------------------------
    # Här bygger du senare:
    # - FRED calls
    # - scoring
    # - trend detection
    #
    # Just nu: stabil mock-logik
    score = 0

    status_key = determine_status(score, cfg)
    status_label = cfg["status_levels"][status_key]["label"]

    payload = {
        "project": cfg["project"]["name"],
        "mode": mode,
        "timestamp": now_utc(),
        "score": score,
        "status": {
            "level": status_key,
            "label": status_label
        },
        "notes": "Initial scaffold – no live indicators yet"
    }

    latest_path = os.path.join(data_dir, out_cfg["latest_file"])
    with open(latest_path, "w") as f:
        json.dump(payload, f, indent=2)

    print(f"[OK] Updated {latest_path}")
    print(f"[INFO] Mode={mode}, Status={status_key.upper()}, Score={score}")

def main():
    parser = argparse.ArgumentParser(description="SolonInsight dashboard updater")
    parser.add_argument(
        "--mode",
        choices=["daily", "weekly", "monthly"],
        required=True,
        help="Execution mode"
    )
    args = parser.parse_args()

    run_dashboard(args.mode)

if __name__ == "__main__":
    main()
