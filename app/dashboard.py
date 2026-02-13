#!/usr/bin/env python3
import argparse
import json
import os
import sys
import yaml
import time
from datetime import datetime

try:
    import requests
except ImportError:
    sys.exit("ERROR: requests library not installed. Run: pip install -r app/requirements.txt")

BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
APP_DIR = os.path.dirname(__file__)

def load_env_file(env_path):
    """
    Load .env file and set environment variables.
    Simple parser: handles KEY=VALUE lines, ignores comments and blanks.
    """
    if not os.path.exists(env_path):
        return
    
    try:
        with open(env_path, "r") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                if "=" in line:
                    key, value = line.split("=", 1)
                    key = key.strip()
                    value = value.strip()
                    # Only set if not already in environment (env vars take precedence)
                    if key not in os.environ:
                        os.environ[key] = value
    except Exception as e:
        print(f"[WARN] Could not load .env file: {e}")

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

def fetch_fred_series(series_id, api_key, timeout=15, max_retries=2):
    """
    Fetch latest observation from FRED series.
    Returns (value, obs_date) on success, (None, None) on error.
    """
    if not api_key:
        return None, None, "FRED API key not configured (set FRED_API_KEY env var)"
    
    url = "https://api.stlouisfed.org/fred/series/observations"
    params = {
        "series_id": series_id,
        "api_key": api_key,
        "units": "lin",
        "limit": 1,
        "sort_order": "desc"
    }
    
    for attempt in range(max_retries):
        try:
            resp = requests.get(url, params=params, timeout=timeout)
            
            # Check HTTP status
            if resp.status_code == 400:
                return None, None, "FRED API: Invalid request (check series_id)"
            elif resp.status_code == 401:
                return None, None, "FRED API: Invalid API key (set FRED_API_KEY)"
            elif resp.status_code == 429:
                error_msg = f"FRED API: Rate limited (attempt {attempt+1}/{max_retries})"
                if attempt < max_retries - 1:
                    time.sleep(2 ** (attempt + 2))
                    continue
                return None, None, error_msg
            elif resp.status_code >= 400:
                error_msg = f"FRED API: HTTP {resp.status_code} (attempt {attempt+1}/{max_retries})"
                if 500 <= resp.status_code < 600 and attempt < max_retries - 1:
                    time.sleep(2 ** attempt)
                    continue
                return None, None, error_msg
            
            resp.raise_for_status()
            data = resp.json()
            
            obs = data.get("observations", [])
            if not obs:
                return None, None, "No observations returned from FRED"
            
            latest = obs[0]
            value_str = latest.get("value")
            
            if value_str == "." or not value_str:
                return None, None, "Latest observation is missing/NA"
            
            try:
                value = float(value_str)
                date = latest.get("date", "")
                return value, date, None
            except ValueError:
                return None, None, f"Could not parse value: {value_str}"
        
        except requests.exceptions.Timeout:
            error_msg = f"FRED API timeout (attempt {attempt+1}/{max_retries})"
            if attempt < max_retries - 1:
                time.sleep(2 ** attempt)
                continue
            return None, None, error_msg
        except requests.exceptions.ConnectionError as e:
            error_msg = f"FRED API: Connection error (attempt {attempt+1}/{max_retries})"
            if attempt < max_retries - 1:
                time.sleep(2 ** attempt)
                continue
            return None, None, error_msg
        except requests.exceptions.RequestException as e:
            return None, None, f"FRED API error: {str(e)}"
        except (json.JSONDecodeError, ValueError) as e:
            error_msg = f"Invalid JSON from FRED: {str(e)} (attempt {attempt+1}/{max_retries})"
            if attempt < max_retries - 1:
                time.sleep(1)
                continue
            return None, None, error_msg
    
    return None, None, "Max retries exceeded"

def get_signal_for_value(value, thresholds):
    """Determine signal color based on value and thresholds."""
    if value is None:
        return "unknown"
    if value <= thresholds.get("green_max", float("inf")):
        return "green"
    if value <= thresholds.get("yellow_max", float("inf")):
        return "yellow"
    return "red"

def run_dashboard(mode):
    """
    Fetch enabled indicators and write to latest.json.
    Uses atomic write: temp file → rename.
    """
    # Load .env file from repo root
    env_path = os.path.join(BASE_DIR, ".env")
    load_env_file(env_path)
    
    cfg = load_config()
    
    out_cfg = cfg["output"]
    data_dir = os.path.join(BASE_DIR, out_cfg["data_dir"])
    ensure_dir(data_dir)
    
    # Get API key from environment (.env or system env vars)
    fred_api_key = os.environ.get("FRED_API_KEY")
    
    # Build indicators array
    indicators = []
    
    # Fetch UNRATE
    unrate_cfg = cfg.get("indicators", {}).get("unrate")
    if unrate_cfg:
        print(f"[*] Fetching {unrate_cfg['label']}...")
        value, obs_date, error = fetch_fred_series(
            unrate_cfg["series_id"],
            fred_api_key,
            timeout=15,
            max_retries=2
        )
        
        signal = get_signal_for_value(value, unrate_cfg.get("thresholds", {}))
        
        if error:
            print(f"    [WARN] {error}")
        if value is not None:
            print(f"    [OK] {unrate_cfg['label']} = {value}% ({signal})")
        
        indicator_entry = {
            "key": "unrate",
            "label": unrate_cfg["label"],
            "source": unrate_cfg["source"],
            "timestamp": obs_date if obs_date else now_utc(),
            "value": round(value, 2) if value is not None else None,
            "unit": "%",
            "signal": signal,
            "notes": error if error else unrate_cfg.get("notes", "")
        }
        indicators.append(indicator_entry)
    
    # Build payload
    payload = {
        "project": cfg["project"]["name"],
        "mode": mode,
        "timestamp": now_utc(),
        "indicators": indicators,
        "meta": {
            "version": 1,
            "generated_by": "dashboard.py"
        }
    }
    
    # Atomic write: write to temp, then rename
    latest_path = os.path.join(data_dir, out_cfg["latest_file"])
    temp_path = latest_path + ".tmp"
    
    try:
        with open(temp_path, "w") as f:
            json.dump(payload, f, indent=2)
        
        # Atomic rename
        if os.path.exists(latest_path):
            os.remove(latest_path)
        os.rename(temp_path, latest_path)
        
        print(f"[OK] Updated {latest_path}")
        print(f"[INFO] Indicators: {len(indicators)}, Mode: {mode}")
    except Exception as e:
        print(f"[ERROR] Failed to write {latest_path}: {e}")
        if os.path.exists(temp_path):
            os.remove(temp_path)
        sys.exit(1)

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
