"""Pull all free data needed for the bull/bear replays into the scratchpad."""
import json, sys, time, warnings
warnings.filterwarnings("ignore")
from pathlib import Path
import pandas as pd
import yfinance as yf
import urllib.request

OUT = Path(__file__).parent / "replay_data"
OUT.mkdir(exist_ok=True)

CRYPTO = ["BTC-USD", "ETH-USD", "SOL-USD"]
# diversified liquid US universe + defensives + benchmarks (all trade since <=2015 except noted)
STOCKS = ["AAPL", "MSFT", "NVDA", "AMZN", "GOOGL", "META", "TSLA", "AMD", "AVGO",
          "JPM", "BRK-B", "V", "UNH", "JNJ", "LLY", "PG", "KO", "PEP", "MCD",
          "XOM", "CVX", "CAT", "HON", "GE", "BA", "UPS", "COST", "WMT", "HD",
          "NFLX", "CRM", "ORCL", "ADBE", "INTC", "MU", "QCOM", "TXN",
          "SPY", "QQQ", "IWM", "TLT", "IEF", "GLD", "XLP", "XLU", "XLV", "XLE",
          "XLF", "XLK", "XLI", "SHV"]

def fetch(tickers, start, path):
    px = yf.download(tickers, start=start, auto_adjust=True, progress=False)["Close"]
    px = px.dropna(how="all")
    px.to_csv(path)
    print(f"{path.name}: {px.shape[0]} rows x {px.shape[1]} cols, "
          f"{px.index[0].date()} -> {px.index[-1].date()}")
    return px

fetch(CRYPTO, "2015-01-01", OUT / "crypto_px.csv")
fetch(STOCKS, "2014-12-01", OUT / "stock_px.csv")

# Fear & Greed (alternative.me, full history, free)
try:
    req = urllib.request.Request("https://api.alternative.me/fng/?limit=0&format=json",
                                 headers={"User-Agent": "Mozilla/5.0"})
    d = json.loads(urllib.request.urlopen(req, timeout=30).read())["data"]
    fng = pd.DataFrame([{"date": pd.to_datetime(int(r["timestamp"]), unit="s").date(),
                         "fng": int(r["value"])} for r in d]).set_index("date").sort_index()
    fng.to_csv(OUT / "fng.csv")
    print(f"fng.csv: {len(fng)} days, {fng.index[0]} -> {fng.index[-1]}")
except Exception as e:
    print("F&G fetch failed:", e)

# BTC on-chain active addresses (blockchain.info, free)
try:
    url = "https://api.blockchain.info/charts/n-unique-addresses?timespan=all&format=json&sampled=false"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    d = json.loads(urllib.request.urlopen(req, timeout=60).read())["values"]
    oc = pd.DataFrame([{"date": pd.to_datetime(r["x"], unit="s").date(), "addr": r["y"]}
                       for r in d]).set_index("date").sort_index()
    oc.to_csv(OUT / "onchain.csv")
    print(f"onchain.csv: {len(oc)} days")
except Exception as e:
    print("on-chain fetch failed:", e)
