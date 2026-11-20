"""여러 해 시장 기록 한꺼번에 채우기 (빠른 버전: 종목×날짜 표로 한 번에 계산)

사용: python tools/backfill_years.py 20200102 20251231
- 이미 records/market/날짜.json 이 있는 날은 건너뜀
- 한계: 테마 묶음은 지금 기준, 지금 상장된 종목만 (상장폐지 종목 빠짐), 오른 이유는 테마로만
"""
import os, sys, json
from concurrent.futures import ThreadPoolExecutor
import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
import market_data as md, info, leaders as ld  # noqa: E402

REC = os.path.join(ROOT, "records")
N = 1800


def raw(code):
    try:
        t = md.S.get(f"https://fchart.stock.naver.com/sise.nhn?symbol={code}&timeframe=day&count={N}&requestType=0", timeout=30).text
        d = pd.DataFrame(md._items(t), columns=["date", "o", "h", "l", "c", "v"])
        d[["o", "c", "v"]] = d[["o", "c", "v"]].astype(float)
        return code, d.set_index("date")
    except Exception:
        return code, None


def main(start, end):
    L = md.all_stocks().drop_duplicates("code")
    names = dict(zip(L.code, L.name))
    with ThreadPoolExecutor(12) as ex:
        res = {c: d for c, d in ex.map(raw, L.code) if d is not None and len(d)}
    print("종목", len(res))
    C = pd.DataFrame({c: d.c for c, d in res.items()}).sort_index()
    O = pd.DataFrame({c: d.o for c, d in res.items()}).reindex(C.index)
    V = pd.DataFrame({c: d.v for c, d in res.items()}).reindex(C.index)
    R = (C / C.shift(1) - 1) * 100
    VAL = C * V / 1e8
    NO = (O.shift(-1) / C - 1) * 100
    NC = (C.shift(-1) / C - 1) * 100
    T = info._themes()
    idx = {}
    for k in ("KOSPI", "KOSDAQ"):
        _, d = raw(k)
        idx[k] = (d.c / d.c.shift(1) - 1) * 100
    os.makedirs(os.path.join(REC, "market"), exist_ok=True)
    have = {f[:8] for f in os.listdir(os.path.join(REC, "market"))}
    days = [d for d in C.index if start <= d <= end and d not in have and d in idx["KOSPI"].index]
    print("계산할 날", len(days))
    lead_rows = []
    for n, day in enumerate(days):
        A = pd.DataFrame({"ret": R.loc[day], "value": VAL.loc[day], "price": C.loc[day],
                          "no": NO.loc[day], "nc": NC.loc[day]}).dropna(subset=["ret", "value"])
        A = A[A.price > 0]
        if A.empty:
            continue
        A["code"] = A.index; A["name"] = A.code.map(names)
        tt = ld.top_themes(A, T)
        Ld = ld.leaders(A)
        log = []
        for r in Ld.itertuples():
            th = [t["name"] for t in T if r.code in t["codes"]]
            main_ = next((t["name"] for t in tt if t["name"] in th), th[0] if th else "")
            log.append(dict(date=day, code=r.code, name=r.name, ret=round(r.ret, 2), value=round(r.value), close=r.price,
                            themes="|".join(th[:3]), main_theme=main_, reason=("테마: " + main_) if main_ else "뚜렷한 재료 못 찾음",
                            next_open=round(r.no, 2) if r.no == r.no else None, next_close=round(r.nc, 2) if r.nc == r.nc else None))
        lead_rows += log
        now = A.set_index("code")
        themes = []
        for t in T:
            m = now.reindex([c for c in t["codes"] if c in now.index]).dropna(subset=["ret"])
            if len(m) < 5:
                continue
            m = m.sort_values("ret", ascending=False)
            themes.append(dict(name=t["name"], n=len(m), avg=round(float(m.ret.mean()), 2), up5=int((m.ret >= 5).sum()),
                               lead=m.iloc[0]["name"], lead_ret=round(float(m.iloc[0].ret), 2), second=m.iloc[1]["name"], second_ret=round(float(m.iloc[1].ret), 2)))
        themes.sort(key=lambda z: -z["avg"])
        snap = dict(date=day, kospi=round(float(idx["KOSPI"].get(day, float("nan"))), 2), kosdaq=round(float(idx["KOSDAQ"].get(day, float("nan"))), 2),
                    adv=int((A.ret > 0).sum()), dec=int((A.ret < 0).sum()), flat=int((A.ret == 0).sum()),
                    limit_up=int((A.ret >= 29.5).sum()), limit_down=int((A.ret <= -29.5).sum()), value_total=round(float(A.value.sum())),
                    hot=[dict(name=t["name"], n=t["n"], lead=t["lead"], lead_ret=round(float(t["lead_ret"]), 2), second=t["second"],
                              second_ret=round(float(t["second_ret"]), 2)) for t in tt],
                    themes=themes[:12], themes_worst=themes[-5:][::-1],
                    leaders=[dict(name=r["name"], code=r["code"], ret=r["ret"], value=r["value"], theme=r["main_theme"], reason=r["reason"]) for r in log],
                    backfilled=True)
        json.dump(snap, open(os.path.join(REC, "market", f"{day}.json"), "w"), ensure_ascii=False, indent=0)
        if n % 100 == 0:
            print(n, day, flush=True)
    f = os.path.join(REC, "leaders.csv")
    old = pd.read_csv(f, dtype={"code": str, "date": str}) if os.path.exists(f) else pd.DataFrame()
    new = pd.DataFrame(lead_rows)
    if len(old) and len(new):
        new = new[~new.date.isin(set(old.date))]
    pd.concat([new, old], ignore_index=True).sort_values("date").to_csv(f, index=False)
    print("끝", len(days))


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
