#!/usr/bin/env python3
"""Daily market-numbers refresher — the 'signals and indicators' half of the
daily loop. Pulls every structured dataset the brain feeds on into
data/crypto_history/ (idempotent full-refresh; every source is free, no keys,
no paid APIs) and tops up the Guardian archive. News-text gathering lives in
accumulate_once.py + the GDELT crawler + the X browser protocol; DIGESTION of
anything gathered here is always a Claude Code Sonnet subagent's job.

Run daily from cron before the AI digestion routine.
"""
import io
import csv
import json
import re
import sys
import zipfile
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HIST = ROOT / "data" / "crypto_history"
HIST.mkdir(parents=True, exist_ok=True)


def get(url: str, timeout: int = 40) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (ai-investing/1.0)"})
    return urllib.request.urlopen(req, timeout=timeout).read()


def step(name, fn):
    try:
        msg = fn()
        print(f"  ok  {name}: {msg}", flush=True)
    except Exception as exc:
        print(f"  FAIL {name}: {str(exc)[:90]}", flush=True)


def stablecoins():
    rows = json.loads(get("https://stablecoins.llama.fi/stablecoincharts/all"))
    out = [{"date": r["date"], "usd_bn": round(r["totalCirculatingUSD"]["peggedUSD"] / 1e9, 3)}
           for r in rows if r.get("totalCirculatingUSD", {}).get("peggedUSD")]
    json.dump(out, open(HIST / "stablecoins_daily.json", "w"))
    return f"{len(out)} days, latest ${out[-1]['usd_bn']}bn"


def fear_greed():
    d = json.loads(get("https://api.alternative.me/fng/?limit=0&format=json"))
    rows = [{"ts": int(r["timestamp"]), "value": int(r["value"]),
             "label": r["value_classification"]} for r in d.get("data", [])]
    json.dump(rows, open(HIST / "fear_greed_daily.json", "w"))
    return f"{len(rows)} days, latest {rows[0]['value']} ({rows[0]['label']})"


def etf_flows():
    outs = []
    for name, url in [("btc_etf_flows", "https://farside.co.uk/bitcoin-etf-flow-all-data/"),
                      ("eth_etf_flows", "https://farside.co.uk/ethereum-etf-flow-all-data/")]:
        html = get(url, 60).decode("utf-8", "ignore")
        parsed = []
        for r in re.findall(r"<tr[^>]*>(.*?)</tr>", html, re.S):
            cells = [re.sub(r"<[^>]+>", "", c).strip().replace("&nbsp;", " ")
                     .replace("(", "-").replace(")", "")
                     for c in re.findall(r"<t[dh][^>]*>(.*?)</t[dh]>", r, re.S)]
            if cells and re.match(r"\d{1,2} \w{3} \d{4}", cells[0]):
                parsed.append(cells)
        json.dump(parsed, open(HIST / f"{name}.json", "w"))
        outs.append(f"{name.split('_')[0]} {len(parsed)}d")
        time.sleep(2)
    return ", ".join(outs)


def dvol():
    outs = []
    for cur in ("BTC", "ETH"):
        end = int(time.time() * 1000)
        data, guard = [], 0
        while guard < 40:
            d = json.loads(get(
                "https://www.deribit.com/api/v2/public/get_volatility_index_data"
                f"?currency={cur}&resolution=1D&start_timestamp=1609459200000&end_timestamp={end}"))
            batch = d.get("result", {}).get("data", [])
            if not batch:
                break
            data = batch + data
            end = batch[0][0] - 86400000
            guard += 1
            time.sleep(0.4)
        rows = [{"ts": r[0] // 1000, "open": r[1], "high": r[2], "low": r[3], "close": r[4]}
                for r in data]
        json.dump(rows, open(HIST / f"dvol_{cur.lower()}.json", "w"))
        outs.append(f"{cur} {len(rows)}d")
    return ", ".join(outs)


def cot():
    """CFTC TFF: refresh current + previous year, keep earlier history."""
    path = HIST / "cftc_cot_crypto.json"
    old = json.loads(path.read_text()) if path.exists() else []
    yr_now = datetime.now(timezone.utc).year
    keep = [r for r in old if int(r["date"][:4]) < yr_now - 1]
    for yr in (yr_now - 1, yr_now):
        z = zipfile.ZipFile(io.BytesIO(get(
            f"https://www.cftc.gov/files/dea/history/fut_fin_txt_{yr}.zip", 120)))
        rdr = csv.reader(io.TextIOWrapper(z.open(z.namelist()[0]), errors="ignore"))
        next(rdr)
        for row in rdr:
            if row and ("BITCOIN" in row[0].upper() or "ETHER" in row[0].upper()):
                keep.append({"market": row[0].strip(), "date": row[2].strip(),
                             "oi": row[7], "asset_mgr_long": row[10],
                             "asset_mgr_short": row[11], "lev_long": row[13],
                             "lev_short": row[14]})
    json.dump(keep, open(path, "w"))
    return f"{len(keep)} weekly rows"


def guardian():
    sys.path.insert(0, str(ROOT / "engine"))
    from ai_investing.research import guardian_fetch
    rc = guardian_fetch.run()
    return f"exit {rc} (archive topped up)"


if __name__ == "__main__":
    print(f"[{datetime.now(timezone.utc):%Y-%m-%d %H:%M}] market-data refresh", flush=True)
    step("stablecoins (DefiLlama)", stablecoins)
    step("fear&greed (alternative.me)", fear_greed)
    step("ETF flows (Farside)", etf_flows)
    step("DVOL (Deribit)", dvol)
    step("CFTC COT", cot)
    step("Guardian archive", guardian)
    print("refresh complete", flush=True)
