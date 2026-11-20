"""15분봉 MACD·일목 단타 모의매매 (MACD 골든크로스·일목 구름·이평 수렴·RSI·스토캐스틱·파라볼릭) — 매일 기록용

규칙 (프로젝트 문서 '아버지-분봉단타-검증-결과' 3장)
  매수: 09:15~14:45 신호, 전날 거래대금 300억↑, MACD 골든크로스(최근 3봉), 10·20선 2%·20·60선 3% 이내,
        10선 상승, 일목 구름 위, 선행스팬1 상승, RSI 50↑, 스토캐스틱 슬로우 %K 40↑, 파라볼릭 매수 상태,
        다이버전스(20봉 신고가인데 MACD·스토캐스틱 약해짐) 제외 → 다음 봉 시가 매수
  매도: TSF(10) 꺾이면 다음 봉 시가 / 손절 -2% / 장 마감 종가
  모의 운용: 하루 최대 3건, 1건당 100만원, 신호 먼저 뜬 순서. 비용 0.35% 뺌

데이터 한계
  - 네이버 1분봉(최근 6거래일, 1분 종가만)으로 15분봉을 만듦 → 고가·저가는 1분 종가 기준 근사
  - 200선(15분봉 200개 ≈ 8일)은 데이터가 모자라 뺌 (검증에서 '200선 빼기'도 성적 거의 같았음: -0.40%)
  - 지표 준비에 3일이 필요해서, 받은 6일 중 뒤 3일만 매매 기록

사용: python father_mock.py            → 최근 3거래일 모의매매 출력 + records/father_mock.csv
"""
import os, re, sys
import numpy as np
import pandas as pd
import market_data as md

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = f"{HERE}/records/father_mock.csv"
COST, STOP, MAX_PER_DAY, SEED = 0.35, 2.0, 3, 1_000_000
S = md.S


# ---------- 지표 (검증 때와 같은 계산) ----------
def rsi(c, n=14):
    d = c.diff()
    up = d.clip(lower=0).ewm(alpha=1 / n, adjust=False).mean()
    dn = (-d.clip(upper=0)).ewm(alpha=1 / n, adjust=False).mean()
    return 100 - 100 / (1 + up / dn.replace(0, np.nan))


def stoch_slow(h, l, c, n=5, k=3, d=3):
    fast = 100 * (c - l.rolling(n).min()) / (h.rolling(n).max() - l.rolling(n).min()).replace(0, np.nan)
    sk = fast.rolling(k).mean()
    return sk, sk.rolling(d).mean()


def macd(c):
    m = c.ewm(span=12, adjust=False).mean() - c.ewm(span=26, adjust=False).mean()
    return m, m.ewm(span=9, adjust=False).mean()


def sar_up(h, l, af0=0.02, step=0.02, afmax=0.2):
    h, l = h.values, l.values
    n = len(h); tr = np.zeros(n, dtype=int)
    if n < 3:
        return tr
    up = h[1] >= h[0]; sar = l[0] if up else h[0]; ep = h[1] if up else l[1]; af = af0
    tr[0] = tr[1] = 1 if up else -1
    for i in range(2, n):
        sar = sar + af * (ep - sar)
        if up:
            sar = min(sar, l[i - 1], l[i - 2])
            if l[i] < sar: up = False; sar = ep; ep = l[i]; af = af0
            elif h[i] > ep: ep = h[i]; af = min(af + step, afmax)
        else:
            sar = max(sar, h[i - 1], h[i - 2])
            if h[i] > sar: up = True; sar = ep; ep = h[i]; af = af0
            elif l[i] < ep: ep = l[i]; af = min(af + step, afmax)
        tr[i] = 1 if up else -1
    return tr


def tsf(c, n=10):
    x = np.arange(n); xm = x.mean(); den = ((x - xm) ** 2).sum()
    def f(y):
        b = ((x - xm) * (y - y.mean())).sum() / den
        return y.mean() - b * xm + b * n
    return c.rolling(n).apply(f, raw=True)


# ---------- 데이터 ----------
def daily_raw(code, n=12):
    t = S.get(f"https://fchart.stock.naver.com/sise.nhn?symbol={code}&timeframe=day&count={n}&requestType=0", timeout=15).text
    df = pd.DataFrame(md._items(t), columns=["date", "o", "h", "l", "c", "v"])
    df[["c", "v"]] = df[["c", "v"]].astype(float)
    return df


def bars15(code):
    t = S.get(f"https://fchart.stock.naver.com/sise.nhn?symbol={code}&timeframe=minute&count=3000&requestType=0", timeout=15).text
    m = pd.DataFrame(md._items(t), columns=["t", "o", "h", "l", "c", "v"])
    if m.empty:
        return m
    m = m[(m.t.str[8:12] >= "0900") & (m.t.str[8:12] < "1530")].copy()
    m["c"] = m.c.astype(float)
    m["date"] = m.t.str[:8]
    hm = m.t.str[8:10].astype(int) * 60 + m.t.str[10:12].astype(int)
    m["slot"] = ((hm - 540) // 15).astype(int)
    g = m.groupby(["date", "slot"]).c
    b = pd.DataFrame(dict(open=g.first(), high=g.max(), low=g.min(), close=g.last())).reset_index()
    b["hm"] = 900 + (b.slot * 15 // 60) * 100 + (b.slot * 15) % 60
    return b.sort_values(["date", "slot"]).reset_index(drop=True)


def add(x):
    c, h, l = x.close, x.high, x.low
    for n in (10, 20, 60):
        x[f"ma{n}"] = c.rolling(n).mean()
    x["rsi"] = rsi(c)
    x["sk"], x["sd"] = stoch_slow(h, l, c)
    x["macd"], x["sig"] = macd(c)
    conv = (h.rolling(9).max() + l.rolling(9).min()) / 2
    base = (h.rolling(26).max() + l.rolling(26).min()) / 2
    s1 = (conv + base) / 2
    s2 = (h.rolling(52).max() + l.rolling(52).min()) / 2
    x["span1"] = s1
    x["cloud"] = pd.concat([s1.shift(26), s2.shift(26)], axis=1).max(axis=1)
    x["sar"] = sar_up(h, l)
    x["tsf"] = tsf(c)
    return x


def signal(x):
    gc = (x.macd > x.sig) & (x.macd.shift(1) <= x.sig.shift(1))
    ok = (x.hm >= 915) & (x.hm <= 1445) & (x.tv_prev >= 300e8)
    ok &= gc.rolling(3).max().fillna(0).astype(bool)
    ok &= (x.ma10 - x.ma20).abs() / x.close * 100 <= 2
    ok &= (x.ma20 - x.ma60).abs() / x.close * 100 <= 3
    ok &= x.ma10 > x.ma10.shift(1)
    ok &= x.close > x.cloud
    ok &= x.span1 > x.span1.shift(1)
    ok &= x.rsi >= 50
    ok &= x.sk >= 40
    ok &= x.sar == 1
    new_hi = x.close >= x.close.rolling(20).max()
    weak = (x.macd < x.macd.rolling(20).max()) & (x.sk < x.sk.shift(1))
    ok &= ~(new_hi & weak)
    return ok.fillna(False)


def trade(x, i):
    """신호 봉 i → 다음 봉 시가 매수, 매도 규칙대로. 반환 dict 또는 None"""
    e = i + 1
    if e >= len(x) or x.date[e] != x.date[i]:
        return None
    ep = x.open[e]; stop = ep * (1 - STOP / 100)
    j = e
    while j < len(x):
        last = j + 1 >= len(x) or x.date[j + 1] != x.date[j]
        if x.low[j] <= stop:
            return dict(e=e, x=j, buy=ep, sell=min(x.open[j], stop) if j > e else stop, why="손절")
        if j > e and x.tsf[j] < x.tsf[j - 1] and not last:
            return dict(e=e, x=j + 1, buy=ep, sell=x.open[j + 1], why="TSF 꺾임")
        if last:
            return dict(e=e, x=j, buy=ep, sell=x.close[j], why="장 마감")
        j += 1
    return None


def hm_text(v):
    return f"{v // 100:02d}:{v % 100:02d}"


def run(days_back=3):
    L = md.all_stocks()
    pool = L.sort_values("value", ascending=False).head(250)
    events = []
    for r in pool.itertuples():
        try:
            d = daily_raw(r.code)
            d["tv"] = d.c * d.v
            prev_tv = dict(zip(d.date, d.tv.shift(1)))
            if max([v for v in list(prev_tv.values())[-days_back:] if v == v] or [0]) < 300e8:
                continue
            x = bars15(r.code)
            if len(x) < 100:
                continue
            x["tv_prev"] = x.date.map(prev_tv)
            x = add(x)
            days = sorted(x.date.unique())[-days_back:]
            sig = signal(x)
            busy = -1
            for i in np.flatnonzero(sig.values):
                if x.date[i] not in days or i <= busy:
                    continue
                t = trade(x, i)
                if t is None:
                    continue
                busy = t["x"]
                events.append(dict(date=x.date[t["e"]], t_in=int(x.hm[t["e"]]), t_out=int(x.hm[min(t["x"], len(x) - 1)]),
                                   code=r.code, name=r.name, buy=t["buy"], sell=t["sell"], why=t["why"]))
        except Exception as ex:
            print("건너뜀", r.code, ex.__class__.__name__, file=sys.stderr)
    ev = pd.DataFrame(events)
    if ev.empty:
        return ev
    ev = ev.sort_values(["date", "t_in"]).groupby("date").head(MAX_PER_DAY).reset_index(drop=True)
    ev["qty"] = (SEED // ev.buy).astype(int)
    ev["stop_px"] = ev.buy * (1 - STOP / 100)
    ev["ret"] = (ev.sell / ev.buy - 1) * 100 - COST
    return ev


def daily_section():
    """19:00 저녁 정리용: 오늘 모의매매만 계산해 records/father_mock.csv에 더하고 요약 문구 반환"""
    ev = run(days_back=1)
    old = pd.read_csv(OUT, dtype={"code": str, "date": str}) if os.path.exists(OUT) else pd.DataFrame()
    if len(ev):
        ev["qty"] = ev.qty.clip(lower=1)
        if len(old):
            old = old[old.date != ev.date.iloc[0]]
        old = pd.concat([old, ev], ignore_index=True)
        old.to_csv(OUT, index=False)
    import html as _h
    lines = ["<b>📐 15분봉 MACD·일목 단타 모의매매</b> (1건 100만원)"]
    if ev.empty:
        lines.append("오늘 신호 없음")
    else:
        rows = [f"{hm_text(r.t_in)}→{hm_text(r.t_out)} {r.ret:+6.2f}%  {_h.escape(r.name)} ({r.why})" for r in ev.itertuples()]
        lines.append("<pre>" + "\n".join(rows) + "</pre>")
    if len(old):
        o = old.ret.astype(float)
        lines.append(f"누적 {len(o)}건 | 승률 {(o > 0).mean() * 100:.0f}% | 평균 {o.mean():+.2f}%\n(비용 0.35% 뺌, 1년 검증 기대 -0.4%)")
    return "\n".join(lines)


if __name__ == "__main__":
    if "--today" in sys.argv:
        print(daily_section()); sys.exit()
    ev = run()
    if len(ev):
        ev["qty"] = ev.qty.clip(lower=1)
    if len(ev):
        ev.to_csv(OUT, index=False)
    pd.set_option("display.width", 200)
    print(ev.to_string() if len(ev) else "신호 없음")
