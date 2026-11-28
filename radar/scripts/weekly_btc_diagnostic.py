"""Read-only Coinbase weekly diagnostic; not TradingView INDEX or formal authority."""
import datetime as dt
import json
import math
import urllib.parse
import urllib.request

DAY = 86400
WEEK = 7 * DAY

def calculate(bars, cutoff):
    if len(bars) < 200:
        raise ValueError("insufficient completed weeks")
    times = sorted(bars)
    if times[-1] != cutoff - WEEK or any(b-a != WEEK for a,b in zip(times,times[1:])):
        raise ValueError("weekly gap or stale cutoff")
    closes = [bars[t] for t in times]
    if any(not math.isfinite(c) or c <= 0 for c in closes):
        raise ValueError("invalid close")
    changes = [b-a for a,b in zip(closes,closes[1:])]
    gain = sum(max(x,0) for x in changes[:14])/14
    loss = sum(max(-x,0) for x in changes[:14])/14
    for x in changes[14:]:
        gain = (13*gain+max(x,0))/14
        loss = (13*loss+max(-x,0))/14
    rsi = 100*gain/(gain+loss) if gain+loss else None
    return {"rsi14":rsi,"sma50":sum(closes[-50:])/50,"sma200":sum(closes[-200:])/200,"completed_weeks":len(closes),"last_close":closes[-1]}

def main():
    now = dt.datetime.now(dt.timezone.utc)
    monday = (now-dt.timedelta(days=now.weekday())).replace(hour=0,minute=0,second=0,microsecond=0)
    cutoff = int(monday.timestamp())
    start = cutoff-260*WEEK
    daily = {}
    for a in range(start,cutoff,250*DAY):
        b = min(a+250*DAY,cutoff)
        params = urllib.parse.urlencode({"granularity":86400,"start":dt.datetime.fromtimestamp(a,dt.timezone.utc).isoformat(),"end":dt.datetime.fromtimestamp(b,dt.timezone.utc).isoformat()})
        url = "https://api.exchange.coinbase.com/products/BTC-USD/candles?"+params
        with urllib.request.urlopen(urllib.request.Request(url,headers={"User-Agent":"CRT read-only diagnostic"}),timeout=20) as response:
            rows = json.load(response)
        for row in rows:
            t = row[0]
            if a <= t < b:
                if t % DAY or t in daily:
                    raise ValueError("invalid or duplicate daily timestamp")
                daily[t] = float(row[4])
    if set(daily) != set(range(start,cutoff,DAY)):
        raise ValueError("missing completed UTC daily bars")
    weeks = {t:daily[t+6*DAY] for t in range(start,cutoff,WEEK)}
    result = calculate(weeks,cutoff)
    result.update(source="Coinbase Exchange BTC-USD",scope="RESEARCH_PROXY_ONLY",formal_authority="NONE",cutoff_utc=monday.isoformat(),retrieved_at_utc=dt.datetime.now(dt.timezone.utc).isoformat())
    print(json.dumps(result,allow_nan=False))

if __name__ == "__main__":
    main()
