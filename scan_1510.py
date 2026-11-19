"""15:10 종가베팅 후보 알림"""
import json, os, sys, time, datetime as dt
import pandas as pd
from config import CFG, PROFILE, KOSDAQ_BREAK, NASDAQ_FUT_BREAK
import market_data as md
from telegram import send
import info

HERE = os.path.dirname(os.path.abspath(__file__))
MOOD = {}   # 오늘 장세 (info.market_mood 결과)


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


def dad_marks(d, price, ret):
    """아버지 종가매매 기준 표시용 (11년 검증: 거르는 조건으로 쓰면 성적이 떨어져서 표시만 함)"""
    c, h, l = d.c.copy(), d.h, d.l
    c.iloc[-1] = price
    jung = cloud = None
    if len(c) >= 120:
        m5, m20, m60, m120 = (c.iloc[-n:].mean() for n in (5, 20, 60, 120))
        jung = m5 > m20 > m60 > m120
    if len(d) >= 78:
        e = len(d) - 26                     # 26일 전까지 데이터로 그린 오늘 자리의 구름
        hh, ll = h.iloc[:e], l.iloc[:e]
        s1 = ((hh.iloc[-9:].max() + ll.iloc[-9:].min()) / 2 + (hh.iloc[-26:].max() + ll.iloc[-26:].min()) / 2) / 2
        s2 = (hh.iloc[-52:].max() + ll.iloc[-52:].min()) / 2
        cloud = price > max(s1, s2)
    return dict(dad_jung=jung, dad_cloud=cloud, dad_10=ret >= 10)


def scan():
    L = md.all_stocks()
    L = L[(L.ret >= CFG["ret_min"]) & (L.ret <= CFG["ret_max"]) & (L.value >= CFG["value_min"])]
    rows = []
    for r in L.itertuples():
        d = md.daily(r.code, 160)
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
                         afternoon=(aft_high is not None and aft_high >= t.h * 0.99),
                         **dad_marks(d, r.price, r.ret)))
    df = pd.DataFrame(rows)
    if df.empty:
        return df
    ok = (df.gap_high >= -CFG["near_high"]) & (df.vol_mult >= CFG["vol_mult"])
    if CFG["need_new_high"]:
        ok &= df.new_high
    if CFG["need_vwap_afternoon"]:
        ok &= df.above_vwap & df.afternoon
    df = df[ok].copy()
    # 같은 테마 대장이 상한가인 2등주를 먼저 고름 (검증: 신호당 +1.65%, 일반 +0.2%)
    try:
        A = md.all_stocks()
        df["second"] = [info.theme_info(c, A)["second_to_limit"] for c in df.code]
    except Exception as e:
        print("테마 확인 실패", e)
        df["second"] = False
    # 그날 상승률 1등 테마 소속이면 🔥 표시만 (11년: +0.63% vs +0.16%). 순서는 바꾸지 않음
    df["hot"] = df.code.isin(MOOD.get("top_codes", set()))
    return df.sort_values(["second", CFG["sort_by"]], ascending=False)


def fmt(p, i):
    lead = " ★대장주급(1000억+)" if p.value >= 1000 else ""
    if p.get("hot", False):
        lead += " 🔥오늘 1등 테마"
    return (f"{i}. {p['name']} ({p.code}){lead}\n"
            f"   현재가 {p.price:,.0f}원 | 등락률 {p.ret:+.1f}% | 거래대금 {p.value:,.0f}억\n"
            f"   고가 대비 {p.gap_high:+.1f}% | 거래량 {p.vol_mult:.1f}배 | 20일 신고가 {'O' if p.new_high else 'X'}\n"
            f"   VWAP {'위' if p.above_vwap else '아래'} | 13시 이후 고가 유지 {'O' if p.afternoon else 'X'}\n"
            f"   아버지 기준(참고) 정배열 {ox(p.get('dad_jung'))} | 구름 위 {ox(p.get('dad_cloud'))} | 10%↑ {ox(p.get('dad_10'))}")


def ox(v):
    return "-" if v is None or v != v else ("O" if v else "X")


def main():
    os.makedirs(f"{HERE}/records", exist_ok=True)
    mark = f"{HERE}/records/sent_1510.txt"
    if "--now" not in sys.argv:
        # 자동 실행이 늦게 깨서 15:25가 넘었거나, 오늘 이미 보냈으면 보내지 않음 (중복·쓸모없는 알림 방지)
        if dt.datetime.now(md.KST).strftime("%H:%M") > "15:25":
            print("너무 늦게 깨서 오늘 15:10 알림은 건너뜀"); return
        if os.path.exists(mark) and open(mark).read().strip() == md.today():
            print("오늘 이미 보냄"); return
        try:   # 테마·DART 목록은 일주일에 한 번 새로 받는데 1~2분 걸려서, 기다리는 동안 미리 받음
            info._themes()
            if info.KEY:
                info._corpmap()
        except Exception as e:
            print("목록 미리 받기 실패", e)
        wait_until("15:08")
    open(mark, "w").write(md.today())
    ok, mtxt = market_check()
    if ok is None:
        print(mtxt); return
    head = f"📊 종가베팅 15:10 ({PROFILE})\n{mtxt}"
    try:
        cal = info.calendar_note()
        if cal:
            head += "\n" + cal
    except Exception as e:
        print("일정 확인 실패", e)
    try:
        import swing
        due = swing.due_today()
        if due:
            head = "⏰ 스윙 A 오늘 종가 매도\n" + "\n".join(due) + "\n\n" + head
    except Exception as e:
        print("스윙 매도 확인 실패", e)
    if not ok:
        send(head); _extras(); return
    try:
        MOOD.update(info.market_mood(md.all_stocks()))
        head += "\n" + MOOD["text"]
    except Exception as e:
        print("장세 확인 실패", e)
    df = scan()
    if df.empty:
        send(head + "\n\n조건에 맞는 종목 없음"); _extras(); return
    picks = df.head(CFG["max_picks"])
    body = "\n\n".join(fmt(p, i + 1) + "\n" + _info_lines(p.code) for i, (_, p) in enumerate(picks.iterrows()))
    more = f"\n\n(그 밖에 {len(df) - len(picks)}종목 더 걸림: " + ", ".join(df.iloc[len(picks):len(picks) + 5]["name"]) + ")" if len(df) > len(picks) else ""
    tip = ("\n\n👉 15:27~15:29 예상체결가가 15:20 가격보다 밀리지 않았는지 확인 후, 현재가 +1~2% 지정가로 매수"
           "\n👉 매수 후 봇에게 보내기: 매수 종목명 수량 체결가  (예: 매수 삼성전자 25 191300)")
    send(head + "\n\n" + body + more + tip)
    os.makedirs(f"{HERE}/records", exist_ok=True)
    picks.to_csv(f"{HERE}/records/picks_{md.today()}.csv", index=False)
    _extras()


def _info_lines(code):
    """고른 종목에만: 테마 순위·오늘 뉴스·공시 경고 (실패해도 알림은 보냄)"""
    try:
        t = info.theme_info(code, md.all_stocks())["text"]
    except Exception:
        t = "   테마: 못 받음"
    return "\n".join([t, info.news_line(code), info.dart_safe_line(code)])


def _extras():
    """종가베팅 알림 뒤에 다른 매매법 알림을 따로 보냄 (하나가 실패해도 나머지는 보냄)"""
    try:
        import lowbuy
        send(lowbuy.preview(), html=True)
    except Exception as e:
        send(f"(저가매수 확인 실패: {e})")
    try:
        import canslim
        send(canslim.today_signals())
    except Exception as e:
        send(f"(중기 스윙 확인 실패: {e})")


if __name__ == "__main__":
    main()
