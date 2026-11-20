"""지나간 날짜의 시장 기록(records/market/날짜.json)과 대장주(records/leaders.csv)를 일봉으로 채우기

뉴스·공시는 지난 것을 못 받아서 '오른 이유'는 테마로만 적는다.
사용: python tools/backfill_market.py 20261102 20261119
"""
import os, sys, json
from concurrent.futures import ThreadPoolExecutor
import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
import market_data as md, info  # noqa: E402

REC = os.path.join(ROOT, "records")


def raw_daily(code, n=40):
    try:
        t = md.S.get(f"https://fchart.stock.naver.com/sise.nhn?symbol={code}&timeframe=day&count={n}&requestType=0", timeout=15).text
        d = pd.DataFrame(md._items(t), columns=["date", "o", "h", "l", "c", "v"])
        d[["o", "c", "v"]] = d[["o", "c", "v"]].astype(float)
        return code, d
    except Exception:
        return code, None


def main(start, end):
    L = md.all_stocks()
    names = dict(zip(L.code, L.name))
    with ThreadPoolExecutor(12) as ex:
        res = dict(ex.map(raw_daily, L.code))
    T = info._themes()
    idx = {k: raw_daily(k)[1] for k in ("KOSPI", "KOSDAQ")}
    days = [d for d in idx["KOSPI"].date if start <= d <= end]
    lead_rows = []
    import leaders as ld
    for day in days:
        rows = []
        for code, d in res.items():
            if d is None or day not in set(d.date):
                continue
            i = d.index[d.date == day][0]
            if i == 0:
                continue
            c, pc = d.c[i], d.c[i - 1]
            nx = d.iloc[i + 1] if i + 1 < len(d) else None
            rows.append(dict(code=code, name=names.get(code, code), price=c, ret=(c / pc - 1) * 100, value=c * d.v[i] / 1e8,
                             next_open=(nx.o / c - 1) * 100 if nx is not None else None, next_close=(nx.c / c - 1) * 100 if nx is not None else None))
        A = pd.DataFrame(rows)
        if A.empty:
            continue
        tt = ld.top_themes(A, T)
        Ld = ld.leaders(A)
        log = []
        for r in Ld.itertuples():
            th = [t["name"] for t in T if r.code in t["codes"]]
            main = next((t["name"] for t in tt if t["name"] in th), th[0] if th else "")
            log.append(dict(date=day, code=r.code, name=r.name, ret=round(r.ret, 2), value=round(r.value), close=r.price,
                            themes="|".join(th[:3]), main_theme=main, reason=("테마: " + main) if main else "뚜렷한 재료 못 찾음",
                            next_open=round(r.next_open, 2) if r.next_open == r.next_open and r.next_open is not None else None,
                            next_close=round(r.next_close, 2) if r.next_close == r.next_close and r.next_close is not None else None))
        lead_rows += log
        # 시장 한 장
        x = A
        now = x.set_index("code")
        themes = []
        for t in T:
            m = now.reindex([c for c in t["codes"] if c in now.index]).dropna(subset=["ret"])
            if len(m) < 5:
                continue
            m = m.sort_values("ret", ascending=False)
            themes.append(dict(name=t["name"], n=len(m), avg=round(float(m.ret.mean()), 2), up5=int((m.ret >= 5).sum()),
                               lead=m.iloc[0]["name"], lead_ret=round(float(m.iloc[0].ret), 2), second=m.iloc[1]["name"], second_ret=round(float(m.iloc[1].ret), 2)))
        themes.sort(key=lambda z: -z["avg"])
        ix = {}
        for k, d in idx.items():
            i = d.index[d.date == day][0]
            ix[k] = round((d.c[i] / d.c[i - 1] - 1) * 100, 2)
        snap = dict(date=day, kospi=ix["KOSPI"], kosdaq=ix["KOSDAQ"], adv=int((x.ret > 0).sum()), dec=int((x.ret < 0).sum()), flat=int((x.ret == 0).sum()),
                    limit_up=int((x.ret >= 29.5).sum()), limit_down=int((x.ret <= -29.5).sum()), value_total=round(float(x.value.sum())),
                    hot=[dict(name=t["name"], n=t["n"], lead=t["lead"], lead_ret=round(float(t["lead_ret"]), 2), second=t["second"],
                              second_ret=round(float(t["second_ret"]), 2)) for t in tt],
                    themes=themes[:12], themes_worst=themes[-5:][::-1],
                    leaders=[dict(name=r["name"], code=r["code"], ret=r["ret"], value=r["value"], theme=r["main_theme"], reason=r["reason"]) for r in log],
                    backfilled=True)
        os.makedirs(os.path.join(REC, "market"), exist_ok=True)
        json.dump(snap, open(os.path.join(REC, "market", f"{day}.json"), "w"), ensure_ascii=False, indent=0)
        print(day, ix, len(log), "대장주", [t["name"] for t in tt])
    # 대장주 기록 합치기 (이미 있는 날짜는 그대로 둠)
    f = os.path.join(REC, "leaders.csv")
    old = pd.read_csv(f, dtype={"code": str, "date": str}) if os.path.exists(f) else pd.DataFrame()
    new = pd.DataFrame(lead_rows)
    if len(old):
        new = new[~new.date.isin(set(old.date))]
    pd.concat([new, old], ignore_index=True).sort_values("date").to_csv(f, index=False)


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
