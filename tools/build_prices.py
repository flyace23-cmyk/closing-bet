"""대장주 달력용 종목 종가 모음 → docs/px/연도.json

대장주(+10%↑·거래대금 100억↑)에 한 번이라도 오른 종목의 일봉 종가를 연도별로 저장한다.
대장주 달력 페이지가 고른 기간의 '기간 등락률'을 계산할 때 쓴다.
- 처음 한 번: 전체 연도 (python tools/build_prices.py --full)
- 평소: 올해 파일만 새로 받음 (하루 한 번, 이미 최신이면 건너뜀)
값은 네이버 일봉 종가(수정주가). 2026.09.14 이후는 애프터장이 섞인 종가라 소수점 차이가 날 수 있다.
"""
import os, sys, json, glob, re, datetime as dt
from concurrent.futures import ThreadPoolExecutor

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
import market_data as md

OUT = os.path.join(ROOT, "docs", "px")


def leaders_by_year():
    """연도 → {종목코드: 이름}"""
    by = {}
    for f in sorted(glob.glob(os.path.join(ROOT, "records", "market", "*.json"))):
        d = os.path.basename(f)[:8]
        try:
            mk = json.load(open(f, encoding="utf-8"))
        except Exception:
            continue
        for x in mk.get("leaders") or []:
            c = str(x.get("code") or "")
            if re.match(r"^\d{6}$", c):
                by.setdefault(d[:4], {})[c] = x.get("name", "")
    return by


def fetch(code, count):
    try:
        t = md.S.get(f"https://fchart.stock.naver.com/sise.nhn?symbol={code}&timeframe=day&count={count}&requestType=0", timeout=20).text
        return code, {r[0]: round(float(r[4])) for r in md._items(t)}
    except Exception as e:
        print("종가 받기 실패:", code, e)
        return code, {}


def build(years, by, count):
    os.makedirs(OUT, exist_ok=True)
    want = {}
    for y in years:     # 그 해 + 앞뒤 해 대장주 (기간이 연도를 넘어가도 계산되게)
        s = {}
        for yy in (str(int(y) - 1), y, str(int(y) + 1)):
            s.update(by.get(yy, {}))
        want[y] = s
    codes = sorted({c for s in want.values() for c in s})
    with ThreadPoolExecutor(8) as ex:
        px = dict(ex.map(lambda c: fetch(c, count), codes))
    for y in years:
        dates = sorted({d for c in want[y] for d in px.get(c, {}) if d[:4] == y})
        p = {}
        for c in want[y]:
            s = px.get(c, {})
            row = [s.get(d) for d in dates]
            if any(v is not None for v in row):
                p[c] = row
        json.dump(dict(d=dates, p=p, n=want[y]), open(os.path.join(OUT, f"{y}.json"), "w", encoding="utf-8"), ensure_ascii=False, separators=(",", ":"))
        print(f"종가 모음 {y}: 종목 {len(p)}개, 날짜 {len(dates)}일")


def main():
    by = leaders_by_year()
    if not by:
        return
    if "--full" in sys.argv:
        first = min(by)
        days = (dt.date.today() - dt.date(int(first) - 1, 12, 1)).days * 5 // 7 + 30
        build(sorted(by), by, days)
        return
    y = max(by)
    last = max(glob.glob(os.path.join(ROOT, "records", "market", "*.json")))[-13:-5]
    f = os.path.join(OUT, f"{y}.json")
    try:
        cur = json.load(open(f, encoding="utf-8"))
        if cur["d"] and cur["d"][-1] >= last and set(by.get(y, {})) <= set(cur["n"]):
            print("종가 모음 최신이라 건너뜀")
            return
    except Exception:
        pass
    build([y], by, 300)


if __name__ == "__main__":
    main()
