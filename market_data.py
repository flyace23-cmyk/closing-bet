"""네이버 증권·야후에서 데이터 받기"""
import re, time, datetime as dt
import requests, pandas as pd

S = requests.Session()
S.headers["User-Agent"] = "Mozilla/5.0"
KST = dt.timezone(dt.timedelta(hours=9))


def today():
    return dt.datetime.now(KST).strftime("%Y%m%d")


def _items(text):
    return [x.split("|") for x in re.findall(r'data="([^"]+)"', text)]


def daily(symbol, count=80):
    """일봉 (오늘 장중이면 오늘 봉 포함). 종목코드 또는 KOSPI/KOSDAQ

    주의: 네이버 일봉은 2026.09.14부터 고가·저가·종가에 애프터장(~20:00) 거래가 섞여 있다.
    그래서 종목은 그 이후 날짜의 고가·저가·종가를 KRX 정규장 값(야후)으로 바꿔서 돌려준다.
    """
    t = S.get(f"https://fchart.stock.naver.com/sise.nhn?symbol={symbol}&timeframe=day&count={count}&requestType=0", timeout=15).text
    df = pd.DataFrame(_items(t), columns=["date", "o", "h", "l", "c", "v"])
    df[["o", "h", "l", "c", "v"]] = df[["o", "h", "l", "c", "v"]].astype(float)
    if re.match(r"^\d{6}$", str(symbol)) and len(df) and df.date.iloc[-1] >= NXT_START:
        df = _to_krx(symbol, df)
    return df


# ---------- 애프터장 섞인 값 → KRX 정규장 값 ----------
NXT_START = "20260914"      # 네이버 일봉이 애프터장 포함으로 바뀐 날
_SFX, _YH = {}, {}          # 종목별 야후 접미사(KS/KQ), 야후 일봉 (한 번 실행하는 동안 저장)


def _yahoo(code, start):
    """야후 일봉 = KRX 정규장 값 (애프터장 없음). 못 받으면 None"""
    key = (code, start)
    if key in _YH:
        return _YH[key]
    p1 = int(dt.datetime.strptime(start, "%Y%m%d").replace(tzinfo=KST).timestamp())
    p2 = int(dt.datetime.now(KST).timestamp()) + 86400
    out = None
    for sfx in ([_SFX[code]] if code in _SFX else ["KS", "KQ"]):
        for i in range(3):
            try:
                r = S.get(f"https://query1.finance.yahoo.com/v8/finance/chart/{code}.{sfx}?period1={p1}&period2={p2}&interval=1d", timeout=15)
                if r.status_code == 429:
                    time.sleep(3 + i * 3); continue
                res = r.json()["chart"]["result"]
                if not res or "timestamp" not in res[0]:
                    break
                q = res[0]["indicators"]["quote"][0]
                y = pd.DataFrame(dict(ts=res[0]["timestamp"], yo=q["open"], yh=q["high"], yl=q["low"], yc=q["close"])).dropna()
                y["date"] = pd.to_datetime(y.ts + 9 * 3600, unit="s").dt.strftime("%Y%m%d")
                out = y.drop(columns="ts").drop_duplicates("date", keep="last")
                _SFX[code] = sfx
                break
            except Exception:
                time.sleep(1)
        if out is not None:
            break
    _YH[key] = out
    return out


def _to_krx(code, df):
    late = df.date >= NXT_START
    y = _yahoo(code, NXT_START)       # 종목마다 한 번만 받아서 재사용
    if y is None or y.empty:
        print(f"[경고] {code} KRX 종가(야후)를 못 받아 네이버 값(애프터장 포함)을 그대로 씀")
        return df
    m = df.merge(y, on="date", how="left")
    # 수정주가 차이로 값이 어긋나는 날은 바꾸지 않음 (시가가 같을 때만 교체)
    ok = late & m.yc.notna() & ((m.o / m.yo - 1).abs() < 0.005)
    # 오늘 봉은 장 마감(15:30) 뒤에만 바꿈. 장중에는 야후가 늦게 따라오고, 네이버 장중 값이 정확함
    if dt.datetime.now(KST).strftime("%H%M") < "1545":
        ok &= m.date != today()
    for k in "hlc":
        m.loc[ok, k] = m.loc[ok, "y" + k].round(0)
    m["h"] = m[["h", "o", "c"]].max(axis=1)
    m["l"] = m[["l", "o", "c"]].min(axis=1)
    return m[["date", "o", "h", "l", "c", "v"]]


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
