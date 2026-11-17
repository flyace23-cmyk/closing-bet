"""15:10 종가베팅 후보 알림"""
import json, os, sys, time, datetime as dt
import pandas as pd
from config import CFG, PROFILE, KOSDAQ_BREAK, NASDAQ_FUT_BREAK
import market_data as md
from telegram import send

HERE = os.path.dirname(os.path.abspath(__file__))


def wait_until(hm):
    """GitHub 자동 실행은 늦게 깨는 일이 있어 일찍 깨운 뒤 정확한 시각까지 기다림"""
    target = dt.datetime.now(md.KST).replace(hour=int(hm[:2]), minute=int(hm[3:]), second=0)
    while dt.datetime.now(md.KST) < target:
        time.sleep(20)


def market_check():
    ks, kq = md.daily("KOSPI", 70), md.daily("KOSDAQ", 70)
    if ks.date.iloc[-1] != md.today():
        return None, "오늘은 휴장일"
    def ma(df, n): return df.c.iloc[-n:].mean()
    k, q = ks.c.iloc[-1], kq.c.iloc[-1]
    kq_ret = (q / kq.c.iloc[-2] - 1) * 100
    ks_ret = (k / ks.c.iloc[-2] - 1) * 100
    nq = md.nasdaq_futures_change()
    lines = [f"코스피 {ks_ret:+.2f}% | 20일선 {'위' if k > ma(ks, 20) else '아래'} | 60일선 {'위' if k > ma(ks, 60) else '아래'}",
             f"코스닥 {kq_ret:+.2f}% | 20일선 {'위' if q > ma(kq, 20) else '아래'}",
             f"나스닥 선물 {nq:+.2f}%" if nq is not None else "나스닥 선물: 못 받음"]
    if CFG["market_rule"] == "v1":
        ok = k > ma(ks, 20) and k > ma(ks, 60) and q > ma(kq, 20)
    else:
        ok = k > ma(ks, 5) or q > ma(kq, 5) or q > kq.o.iloc[-1]
    reason = "" if ok else "지수 조건 미달"
    if kq_ret <= KOSDAQ_BREAK:
        ok, reason = False, f"코스닥 {kq_ret:+.2f}% (휴식 기준 {KOSDAQ_BREAK}%)"
    if nq is not None and nq <= NASDAQ_FUT_BREAK:
        ok, reason = False, f"나스닥 선물 {nq:+.2f}% (휴식 기준 {NASDAQ_FUT_BREAK}%)"
    return ok, "\n".join(lines) + ("" if ok else f"\n→ 오늘은 쉼: {reason}")


def scan():
    L = md.all_stocks()
    L = L[(L.ret >= CFG["ret_min"]) & (L.ret <= CFG["ret_max"]) & (L.value >= CFG["value_min"])]
    rows = []
    for r in L.itertuples():
        d = md.daily(r.code, 30)
        if len(d) < 22 or d.date.iloc[-1] != md.today():
            continue
        t, past = d.iloc[-1], d.iloc[-21:-1]
        vm = t.v / past.v.mean()
        high20 = d.h.iloc[-20:].max()
        gap_high = (r.price / t.h - 1) * 100
        m = md.minute_today(r.code)
        vwap = (m.c * m.vol).sum() / m.vol.sum() if len(m) and m.vol.sum() > 0 else None
        aft_high = m[m.hm >= "13:00"].c.max() if len(m) else None
        rows.append(dict(code=r.code, name=r.name, price=r.price, ret=r.ret, value=r.value,
                         gap_high=gap_high, vol_mult=vm,
                         new_high=t.h >= high20 * 0.97,
                         above_vwap=(vwap is not None and r.price >= vwap),
                         afternoon=(aft_high is not None and aft_high >= t.h * 0.99)))
    df = pd.DataFrame(rows)
    if df.empty:
        return df
    ok = (df.gap_high >= -CFG["near_high"]) & (df.vol_mult >= CFG["vol_mult"])
    if CFG["need_new_high"]:
        ok &= df.new_high
    if CFG["need_vwap_afternoon"]:
        ok &= df.above_vwap & df.afternoon
    return df[ok].sort_values(CFG["sort_by"], ascending=False)


def fmt(p, i):
    lead = " ★대장주급(1000억+)" if p.value >= 1000 else ""
    return (f"{i}. {p['name']} ({p.code}){lead}\n"
            f"   현재가 {p.price:,.0f}원 | 등락률 {p.ret:+.1f}% | 거래대금 {p.value:,.0f}억\n"
            f"   고가 대비 {p.gap_high:+.1f}% | 거래량 {p.vol_mult:.1f}배 | 20일 신고가 {'O' if p.new_high else 'X'}\n"
            f"   VWAP {'위' if p.above_vwap else '아래'} | 13시 이후 고가 유지 {'O' if p.afternoon else 'X'}")


def main():
    if "--now" not in sys.argv:
        wait_until("15:08")
    ok, mtxt = market_check()
    if ok is None:
        print(mtxt); return
    head = f"📊 종가베팅 15:10 ({PROFILE})\n{mtxt}"
    if not ok:
        send(head); return
    df = scan()
    if df.empty:
        send(head + "\n\n조건에 맞는 종목 없음"); return
    picks = df.head(CFG["max_picks"])
    body = "\n\n".join(fmt(p, i + 1) for i, (_, p) in enumerate(picks.iterrows()))
    more = f"\n\n(그 밖에 {len(df) - len(picks)}종목 더 걸림: " + ", ".join(df.iloc[len(picks):len(picks) + 5]["name"]) + ")" if len(df) > len(picks) else ""
    tip = ("\n\n👉 15:27~15:29 예상체결가가 15:20 가격보다 밀리지 않았는지 확인 후, 현재가 +1~2% 지정가로 매수"
           "\n👉 매수 후 봇에게 보내기: 매수 종목명 수량 체결가  (예: 매수 삼성전자 25 191300)")
    send(head + "\n\n" + body + more + tip)
    os.makedirs(f"{HERE}/records", exist_ok=True)
    picks.to_csv(f"{HERE}/records/picks_{md.today()}.csv", index=False)


if __name__ == "__main__":
    main()
