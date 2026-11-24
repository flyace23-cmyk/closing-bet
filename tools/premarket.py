"""장전 뉴스 브리핑용 자료 모으기 — 넥스트레이드 프리마켓(08:00~08:50) 흐름

쓰는 곳: 매일 아침 Claude 예약 작업이 이 결과를 보고 분석문을 씀 (briefing/구성.md 참고)
실행: python tools/premarket.py          → 사람이 읽는 글
      python tools/premarket.py --json   → 자료 그대로

하는 일
1. 코스피·코스닥 시가총액 상위 종목(각 600개)의 프리마켓 등락률을 네이버에서 받음
2. 오른 종목·내린 종목 상위, 테마별로 묶어서 어느 테마가 강한지 계산 (records/themes.json)
3. 코스피·코스닥 지수가 20일선·60일선 위인지 (어제 종가 기준)
4. 어제 장 마감 강한 테마 (records/market/최근.json)
프리마켓 가격이 하나도 없으면 휴장일로 보고 "휴장"만 출력
"""
import os, sys, json, glob, statistics
import datetime as dt
import requests

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
KST = dt.timezone(dt.timedelta(hours=9))
S = requests.Session()
S.headers["User-Agent"] = "Mozilla/5.0"


def premarket(per_market=600):
    rows = []
    for mkt in ["KOSPI", "KOSDAQ"]:
        for page in range(1, per_market // 100 + 1):
            try:
                st = S.get(f"https://m.stock.naver.com/api/stocks/marketValue/{mkt}?page={page}&pageSize=100",
                           timeout=15).json().get("stocks", [])
            except Exception:
                break
            for s in st:
                o = s.get("overMarketPriceInfo") or {}
                if o.get("tradingSessionType") != "PRE_MARKET":
                    continue
                if not str(o.get("localTradedAt", "")).startswith(dt.datetime.now(KST).strftime("%Y-%m-%d")):
                    continue                                   # 오늘 프리마켓 체결만
                try:
                    r = float(o["fluctuationsRatio"])
                except Exception:
                    continue
                rows.append(dict(mkt=mkt, code=s["itemCode"], name=s["stockName"], ret=r,
                                 cap=s.get("marketValueHangeul", ""), t=str(o.get("localTradedAt", ""))[11:16]))
            if not st:
                break
    return rows


def themes_by_code():
    try:
        data = json.load(open(os.path.join(ROOT, "records", "themes.json"), encoding="utf-8"))["data"]
    except Exception:
        return {}
    m = {}
    for t in data:
        for c in t["codes"]:
            m.setdefault(c, []).append(t["name"])
    return m


def theme_table(rows, tmap, top_n=60):
    """오른 상위 top_n 종목 안에 같은 테마가 몇 개 있는지 → 프리마켓 주도 테마"""
    up = sorted(rows, key=lambda r: -r["ret"])[:top_n]
    dn = sorted(rows, key=lambda r: r["ret"])[:top_n]
    def agg(lst):
        d = {}
        for r in lst:
            for t in tmap.get(r["code"], []):
                d.setdefault(t, []).append(r)
        out = [(t, v) for t, v in d.items() if len(v) >= 3]
        out.sort(key=lambda x: (-len(x[1]), -abs(statistics.mean(r["ret"] for r in x[1]))))
        return out[:6]
    return agg(up), agg(dn)


def index_state():
    try:
        import market_data as md
        out = {}
        for sym in ["KOSPI", "KOSDAQ"]:
            d = md.daily(sym, 80)
            d = d[d.date < md.today()] if d.date.iloc[-1] == md.today() else d   # 어제 종가 기준
            c = d.c.iloc[-1]
            out[sym] = dict(close=round(c, 2), ma20=bool(c > d.c.tail(20).mean()), ma60=bool(c > d.c.tail(60).mean()))
        return out
    except Exception as e:
        return {"error": str(e)}


def yesterday_themes():
    fs = sorted(glob.glob(os.path.join(ROOT, "records", "market", "*.json")))
    if not fs:
        return None
    try:
        j = json.load(open(fs[-1], encoding="utf-8"))
        return dict(date=j.get("date"), kospi=j.get("kospi"), kosdaq=j.get("kosdaq"),
                    themes=[dict(name=t["name"], avg=t.get("avg"), lead=t.get("lead"), second=t.get("second"))
                            for t in j.get("themes", [])[:6]])
    except Exception:
        return None


def collect():
    rows = premarket()
    tmap = themes_by_code()
    res = dict(now=dt.datetime.now(KST).strftime("%Y-%m-%d %H:%M"), count=len(rows))
    if not rows:
        res["closed"] = True
        return res
    for m in ["KOSPI", "KOSDAQ"]:
        v = [r["ret"] for r in rows if r["mkt"] == m]
        if v:
            res[m] = dict(median=round(statistics.median(v), 2), up=sum(x > 0 for x in v), n=len(v))
    srt = sorted(rows, key=lambda r: -r["ret"])
    res["top_up"] = [dict(r, themes=tmap.get(r["code"], [])[:2]) for r in srt[:25]]
    res["top_down"] = [dict(r, themes=tmap.get(r["code"], [])[:2]) for r in srt[::-1][:15]]
    up_t, dn_t = theme_table(rows, tmap)
    res["themes_up"] = [dict(theme=t, n=len(v), avg=round(statistics.mean(r["ret"] for r in v), 2),
                             names=[f'{r["name"]} {r["ret"]:+.1f}%' for r in sorted(v, key=lambda r: -r["ret"])[:5]]) for t, v in up_t]
    res["themes_down"] = [dict(theme=t, n=len(v), avg=round(statistics.mean(r["ret"] for r in v), 2),
                               names=[f'{r["name"]} {r["ret"]:+.1f}%' for r in sorted(v, key=lambda r: r["ret"])[:5]]) for t, v in dn_t]
    res["index"] = index_state()
    res["yesterday"] = yesterday_themes()
    return res


def text(res):
    if res.get("closed"):
        return "휴장 (오늘 프리마켓 체결 없음)"
    L = [f"프리마켓 {res['now']} — 시총 상위 {res['count']}종목"]
    for m in ["KOSPI", "KOSDAQ"]:
        if m in res:
            L.append(f"  {m}: 가운데값 {res[m]['median']:+.2f}%, 오름 {res[m]['up']}/{res[m]['n']}")
    L.append("오른 종목 상위:")
    for r in res["top_up"]:
        L.append(f"  {r['name']} {r['ret']:+.2f}% [{', '.join(r['themes'])}]")
    L.append("내린 종목 상위:")
    for r in res["top_down"]:
        L.append(f"  {r['name']} {r['ret']:+.2f}% [{', '.join(r['themes'])}]")
    L.append("강한 테마 (오른 상위 60종목 중 3개 이상):")
    for t in res["themes_up"]:
        L.append(f"  {t['theme']} {t['n']}개 평균 {t['avg']:+.1f}% — {', '.join(t['names'])}")
    L.append("약한 테마:")
    for t in res["themes_down"]:
        L.append(f"  {t['theme']} {t['n']}개 평균 {t['avg']:+.1f}% — {', '.join(t['names'])}")
    L.append(f"지수 위치(어제 종가): {json.dumps(res.get('index'), ensure_ascii=False)}")
    L.append(f"어제 강한 테마: {json.dumps(res.get('yesterday'), ensure_ascii=False)}")
    return "\n".join(L)


if __name__ == "__main__":
    r = collect()
    print(json.dumps(r, ensure_ascii=False, indent=1) if "--json" in sys.argv else text(r))
