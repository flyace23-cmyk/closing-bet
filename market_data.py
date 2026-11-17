"""네이버 증권·야후에서 데이터 받기"""
import re, datetime as dt
import requests, pandas as pd

S = requests.Session()
S.headers["User-Agent"] = "Mozilla/5.0"
KST = dt.timezone(dt.timedelta(hours=9))


def today():
    return dt.datetime.now(KST).strftime("%Y%m%d")


def _items(text):
    return [x.split("|") for x in re.findall(r'data="([^"]+)"', text)]


def daily(symbol, count=80):
    """일봉 (오늘 장중이면 오늘 봉 포함). 종목코드 또는 KOSPI/KOSDAQ"""
    t = S.get(f"https://fchart.stock.naver.com/sise.nhn?symbol={symbol}&timeframe=day&count={count}&requestType=0", timeout=15).text
    df = pd.DataFrame(_items(t), columns=["date", "o", "h", "l", "c", "v"])
    df[["o", "h", "l", "c", "v"]] = df[["o", "h", "l", "c", "v"]].astype(float)
    return df


def minute_today(code):
    """오늘 1분봉: 시각, 종가, 분당 거래량"""
    t = S.get(f"https://fchart.stock.naver.com/sise.nhn?symbol={code}&timeframe=minute&count=500&requestType=0", timeout=15).text
    rows = [r for r in _items(t) if r[0].startswith(today())]
    df = pd.DataFrame(rows, columns=["t", "o", "h", "l", "c", "v"])
    if df.empty:
        return df
    df["c"] = df.c.astype(float)
    cum = df.v.astype(float)
    df["vol"] = cum.diff().fillna(cum).clip(lower=0)   # 누적 거래량 → 분당 거래량
    df["hm"] = df.t.str[8:10] + ":" + df.t.str[10:12]
    return df


def _num(x):
    try:
        return float(str(x).replace(",", ""))
    except ValueError:
        return 0.0


def all_stocks():
    """코스피·코스닥 보통주 현재가 목록 (ETF·스팩·우선주·리츠 제외)"""
    out = []
    for mkt in ["KOSPI", "KOSDAQ"]:
        page = 1
        while True:
            r = S.get(f"https://m.stock.naver.com/api/stocks/marketValue/{mkt}?page={page}&pageSize=100", timeout=15).json()
            st = r.get("stocks", [])
            if not st:
                break
            for s in st:
                if s.get("stockEndType") != "stock" or not re.match(r"^\d{5}0$", s["itemCode"]):
                    continue
                if re.search("스팩|리츠", s["stockName"]):
                    continue
                if s.get("tradeStopType", {}).get("name") != "TRADING":
                    continue
                out.append(dict(
                    code=s["itemCode"], name=s["stockName"], mkt=mkt,
                    price=_num(s["closePrice"]),
                    ret=_num(s["fluctuationsRatio"]),
                    value=_num(s["accumulatedTradingValue"]) / 100,  # 백만원 → 억
                ))
            page += 1
    return pd.DataFrame(out)


def nasdaq_futures_change():
    """나스닥100 선물 전일 대비 등락률(%). 못 받으면 None"""
    try:
        m = S.get("https://query1.finance.yahoo.com/v8/finance/chart/NQ=F?interval=5m&range=1d", timeout=10).json()["chart"]["result"][0]["meta"]
        return (m["regularMarketPrice"] / m["chartPreviousClose"] - 1) * 100
    except Exception:
        return None
