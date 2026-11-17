"""중기 스윙 — 오닐 CAN SLIM (백테스트: 2007~2026 가격, 2016~2026 실적 포함)

신호 (장 마감 기준으로 검증한 규칙):
  관심: 20일 평균 거래대금 30억+, 종가 >= 52주 최고가의 85%, 종가 > 50일선 > 200일선,
        120일 등락률 상위 20% (RS 80+), 최근 65일 최고가(피벗)가 25일 이상 전 + 그 뒤 하락폭 12~35%
  실적: C = 최근 분기 영업이익 전년 같은 분기 대비 +25% 이상, A = 최근 연간 영업이익 +20% 이상 (둘 다 흑자)
  매수: 종가가 처음으로 피벗을 넘고 피벗 +5% 이내, 거래량 50일 평균의 1.5배 이상 → 그날 종가 매수
  등급: A = C와 A 모두 / B = 둘 중 하나 + 시장 켜짐
  시장: 켜짐 → A 정상·B 절반 / 주의 → A 절반만 / 꺼짐 → 매수 안 함
  매도: 손절 -8%, 3일 안에 피벗 아래 종가 2번이면 정리, +20%에서 절반(나머지 손절선 본전),
        3주 안에 +20%면 8주 보유, 50일선을 평균 이상 거래량으로 이탈하면 정리, 최대 126거래일

15:10 → today_signals(): 오늘 종가 매수 후보 (15:10 기준 추정, 거래량은 1.35배로 완화)
19:00 → evening_section(): 마감 기준 확정 신호 모의 기록, 관심 후보, 보유 종목 관리, 성적
"""
import os, re, json, datetime as dt
from concurrent.futures import ThreadPoolExecutor
import numpy as np
import pandas as pd
import market_data as md
import info as cinfo

HERE = os.path.dirname(os.path.abspath(__file__))
REC = f"{HERE}/records"
LOG = f"{REC}/canslim_mock.csv"      # 마감 기준 신호 모의 기록 (백테스트와 같은 방식)
MINE = f"{REC}/canslim_mine.csv"     # 내가 실제로 산 중기 종목
RSF = f"{REC}/canslim_rs.json"       # 19:00에 계산한 RS 순위 (15:10에 사용)

VALUE_MIN = 30        # 20일 평균 거래대금(억)
NEAR_HIGH = 0.85      # 52주 최고가 대비
RS_MIN = 0.80
BASE_MIN, DEPTH = 25, (0.12, 0.35)
CHASE = 0.05
VOL_MULT, VOL_MULT_1510 = 1.5, 1.35
STOP = 0.08
TARGET = 0.20
MAX_HOLD = 126
COST = 0.25           # 왕복 비용 %
EPS_Q, EPS_A = 0.25, 0.20
SHOW_WATCH = 6


# ---------- 데이터 ----------
def _daily(code, n=270):
    d = md.daily(code, n)
    for k in "ohl":
        d.loc[d[k] <= 0, k] = d.loc[d[k] <= 0, "c"]
    return d[d.c > 0].reset_index(drop=True)


def _fin(code):
    """네이버 실적: (분기 증가율, 연간 증가율, 설명). 예상치(컨센서스)는 쓰지 않음"""
    def rows(kind):
        j = md.S.get(f"https://m.stock.naver.com/api/stock/{code}/finance/{kind}", timeout=15).json()["financeInfo"]
        act = [t["key"] for t in j["trTitleList"] if t["isConsensus"] == "N"]
        row = [r for r in j["rowList"] if r["title"] == "영업이익"][0]["columns"]
        out = {}
        for k in act:
            v = str(row.get(k, {}).get("value", "")).replace(",", "")
            try: out[k] = float(v)
            except ValueError: pass
        return out
    def g(cur, prev):
        return cur / prev - 1 if cur is not None and prev is not None and cur > 0 and prev > 0 else None
    try:
        q, a = rows("quarter"), rows("annual")
    except Exception:
        return None, None, "실적 못 받음"
    gq = ga = None; txt = []
    if q:
        k = max(q); pk = str(int(k[:4]) - 1) + k[4:]
        gq = g(q.get(k), q.get(pk))
        txt.append(f"분기({k[2:4]}.{k[4:]}) {'%+.0f%%' % (gq * 100) if gq is not None else '적자/비교불가'}")
    if a:
        k = max(a); pk = str(int(k[:4]) - 1) + k[4:]
        ga = g(a.get(k), a.get(pk))
        txt.append(f"연간({k[:4]}) {'%+.0f%%' % (ga * 100) if ga is not None else '적자/비교불가'}")
    return gq, ga, " | ".join(txt)


def market_state(sym):
    d = _daily(sym, 260)
    c, v = d.c, d.v
    ma50, ma200 = c.iloc[-50:].mean(), c.iloc[-200:].mean()
    dist = ((c.pct_change() <= -0.002) & (v > v.shift(1))).iloc[-25:].sum()
    last = c.iloc[-1]
    if (dist >= 5 and last < ma50) or last < ma200:
        st = "꺼짐"
    elif dist >= 4 or last < ma50:
        st = "주의"
    else:
        st = "켜짐"
    return st, f"{sym} {st} (50일선 {'위' if last > ma50 else '아래'}, 200일선 {'위' if last > ma200 else '아래'}, 분산일 {int(dist)}회)"


# ---------- 규칙 ----------
def _base(d):
    """마지막 날 기준 피벗·바닥 길이·하락폭 (오늘 제외한 최근 65일)"""
    i = len(d) - 1
    w0 = max(0, i - 65)
    win = d.h.values[w0:i]
    j = int(np.argmax(win)); piv = win[j]
    age = i - (w0 + j)
    depth = 1 - d.l.values[w0 + j:i].min() / piv
    return piv, age, depth


def _price_check(d, rs, vol_mult):
    """가격·거래량 조건. (관심 통과 여부, 돌파 여부, 정보)"""
    if len(d) < 252:
        return False, False, None
    c = d.c
    last, prev = c.iloc[-1], c.iloc[-2]
    ma50, ma200 = c.iloc[-50:].mean(), c.iloc[-200:].mean()
    v50 = d.v.iloc[-51:-1].mean()
    tv20 = (d.c * d.v).iloc[-20:].mean() / 1e8
    hi250 = d.h.iloc[-250:].max()
    piv, age, depth = _base(d)
    watch = (last > ma50 > ma200 and last >= NEAR_HIGH * hi250 and tv20 >= VALUE_MIN
             and rs is not None and rs >= RS_MIN and age >= BASE_MIN and DEPTH[0] <= depth <= DEPTH[1])
    vm = d.v.iloc[-1] / v50 if v50 > 0 else 0
    brk = watch and piv < last <= piv * (1 + CHASE) and prev <= piv and vm >= vol_mult
    info = dict(close=last, pivot=piv, base_days=age, depth=round(depth * 100, 1), vol_mult=round(vm, 2),
                tv20=round(tv20), gap_pivot=round((last / piv - 1) * 100, 1), ma50=ma50)
    return watch, brk, info


def _grade(gq, ga, mst):
    c = gq is not None and gq >= EPS_Q
    a = ga is not None and ga >= EPS_A
    if c and a:
        return {"켜짐": "A", "주의": "A(절반)"}.get(mst)
    if (c or a) and mst == "켜짐":
        return "B(절반)"
    return None


def _rs_table(L):
    """전 종목 120일 등락률 순위 (19:00에 계산해 저장)"""
    def r120(code):
        try:
            d = md.daily(code, 125)
            return code, d.c.iloc[-1] / d.c.iloc[-121] - 1 if len(d) >= 121 and d.c.iloc[-121] > 0 else None
        except Exception:
            return code, None
    with ThreadPoolExecutor(8) as ex:
        res = dict(ex.map(r120, L.code))
    s = pd.Series({k: v for k, v in res.items() if v is not None})
    rank = s.rank(pct=True).round(3).to_dict()
    json.dump(dict(date=md.today(), rank=rank), open(RSF, "w"))
    return rank


def _load_rs():
    try:
        return json.load(open(RSF))["rank"]
    except Exception:
        return {}


def _scan(L, rs, vol_mult):
    """후보 목록: (돌파 신호, 관심 후보)"""
    def one(r):
        try:
            d = _daily(r["code"])
        except Exception:
            return None
        if d.empty or d.date.iloc[-1] != md.today():
            return None
        w, b, info = _price_check(d, rs.get(r["code"]), vol_mult)
        if not w:
            return None
        return dict(code=r["code"], name=r["name"], mkt=r["mkt"], rs=rs.get(r["code"]), breakout=b, **info)
    with ThreadPoolExecutor(8) as ex:
        res = [x for x in ex.map(one, L.to_dict("records")) if x]
    df = pd.DataFrame(res)
    if df.empty:
        return df
    fins = {c: _fin(c) for c in df.code}
    df["gq"] = [fins[c][0] for c in df.code]
    df["ga"] = [fins[c][1] for c in df.code]
    df["fin"] = [fins[c][2] for c in df.code]
    return df


def _markets():
    ks, kq = market_state("KOSPI"), market_state("KOSDAQ")
    return {"KOSPI": ks[0], "KOSDAQ": kq[0]}, f"{ks[1]}\n{kq[1]}"


def _fmt(r, grade):
    stop = r.close * (1 - STOP)
    return (f"[{grade}] {r['name']} ({r.code}) {r.close:,.0f}원\n"
            f"   피벗 {r.pivot:,.0f}원 돌파 {r.gap_pivot:+.1f}% | 거래량 {r.vol_mult:.1f}배 | RS {r.rs * 100:.0f}\n"
            f"   실적: {r.fin}\n"
            f"   손절가 {stop:,.0f}원(-8%) | 1차 목표 {r.close * (1 + TARGET):,.0f}원(+20%, 절반)")


def _dart(r, lines):
    """공시 확인: CB·BW·EB 발행 1년 내면 제외(검증 근거), 나머지는 경고만"""
    try:
        chk = cinfo.dart_check(r.code)
    except Exception as e:
        return True, f"   공시: 확인 실패({e.__class__.__name__})"
    if chk["block"]:
        lines.append(f"🚫 {r['name']} 제외 (공시): " + ", ".join(chk["warn"]))
        return False, ""
    return True, cinfo.dart_line(chk)


# ---------- 15:10 ----------
def today_signals():
    """15:10 알림에 붙일 중기 스윙 매수 후보 (오늘 종가 매수)"""
    mst, mtxt = _markets()
    rs = _load_rs()
    if not rs:
        return "🟣 중기 스윙 (CAN SLIM)\nRS 순위가 아직 없음 (오늘 19:00 저녁 정리 뒤부터 동작)"
    if mst["KOSPI"] == "꺼짐" and mst["KOSDAQ"] == "꺼짐":
        return f"🟣 중기 스윙 (CAN SLIM)\n{mtxt}\n→ 시장 꺼짐: 오늘 매수 신호 없음"
    L = md.all_stocks()
    L = L[(L.ret > 0) & (L.value >= 20)]
    df = _scan(L, rs, VOL_MULT_1510)
    lines = ["🟣 중기 스윙 (CAN SLIM) — 오늘 종가 매수 후보", mtxt]
    sig = []
    if not df.empty:
        for _, r in df[df.breakout].iterrows():
            g = _grade(r.gq, r.ga, mst[r.mkt])
            if g:
                ok, dl = _dart(r, lines)
                if ok:
                    sig.append((g, r, dl))
    if not sig:
        lines.append("오늘 매수 신호 없음")
        return "\n".join(lines)
    sig.sort(key=lambda x: x[0])
    for g, r, dl in sig:
        lines.append(_fmt(r, g) + "\n" + dl)
    lines.append("👉 15:20 이후 가격이 피벗 위·피벗 +5% 이내인지 확인하고 종가에 매수\n"
                 "👉 매수 즉시 키움 자동감시주문으로 손절가(-8%) 걸어 두기\n"
                 "👉 산 뒤 봇에게: 중기 종목명 수량 체결가  (예: 중기 삼성전자 10 191300)\n"
                 "👉 한 종목은 중기 자금의 25%까지 (절반 표시는 12.5%)")
    pd.DataFrame([dict(date=md.today(), code=r.code, name=r["name"], grade=g) for g, r, _ in sig]).to_csv(
        f"{REC}/canslim_1510_{md.today()}.csv", index=False)
    return "\n".join(lines)


# ---------- 매도 규칙 (백테스트와 같은 순서) ----------
def manage(d, buy_date, buy, pivot):
    """buy_date 종가 매수 이후 일봉으로 규칙 적용.
    끝났으면 dict(done=True, ret, why, date), 아니면 dict(done=False, 오늘 상태)"""
    idx = d.index[d.date == buy_date]
    if len(idx) == 0:
        return None
    i = idx[0]
    c, h, l, o, v = d.c.values, d.h.values, d.l.values, d.o.values, d.v.values
    ma50 = d.c.rolling(50).mean().values
    v50 = d.v.rolling(50).mean().shift(1).values
    stop = buy * (1 - STOP)
    pos, realized, half, hold8, below = 1.0, 0.0, False, -1, 0
    for k in range(i + 1, len(d)):
        def end(px, why):
            r = realized + pos * (px / buy - 1)
            return dict(done=True, ret=round(r * 100 - COST, 2), why=why, date=d.date.iloc[k])
        if l[k] <= stop:
            return end(min(o[k], stop), "손절" if stop < buy else "본전 정리")
        if k - i <= 3:
            if c[k] < pivot: below += 1
            if below >= 2:
                return end(c[k], "가짜 돌파")
        if not half and h[k] >= buy * (1 + TARGET):
            if k - i <= 15 and hold8 < 0:
                hold8 = i + 40; stop = max(stop, buy)
            elif k > hold8:
                realized += 0.5 * (max(o[k], buy * (1 + TARGET)) / buy - 1); pos = 0.5; half = True; stop = max(stop, buy)
        if hold8 > 0 and k == hold8 and not half:
            realized += 0.5 * (c[k] / buy - 1); pos = 0.5; half = True
        if k > hold8 and c[k] < ma50[k] and v[k] > v50[k]:
            return end(c[k], "50일선 이탈")
        if k - i >= MAX_HOLD:
            return end(c[k], "최대 보유")
    k = len(d) - 1
    return dict(done=False, days=k - i, now=round((c[k] / buy - 1) * 100, 1), stop=stop, half=half,
                hold8=(hold8 > 0 and k < hold8), hold8_left=max(0, hold8 - k) if hold8 > 0 else 0,
                ma50=ma50[k], below_pivot=below, early=(k - i <= 3), target=buy * (1 + TARGET))


def _todo(name, st, buy, qty=None):
    q = f" {qty}주" if qty else ""
    t = [f"• {name}{q} @ {buy:,.0f}원 → 현재 {st['now']:+.1f}% ({st['days']}일째)"]
    t.append(f"   손절가 {st['stop']:,.0f}원" + (" (본전으로 올림)" if st["stop"] >= buy else " (-8%)"))
    if st["hold8"]:
        t.append(f"   3주 안에 +20% 달성 → 8주 보유 중 (남은 {st['hold8_left']}거래일, 그때 절반 매도)")
    elif not st["half"]:
        t.append(f"   +20% 목표가 {st['target']:,.0f}원에 절반 매도 주문 걸어 두기")
    else:
        t.append("   절반 매도 완료 → 나머지는 50일선을 큰 거래량으로 깨면 매도")
    if st["early"]:
        t.append(f"   매수 3일 안: 피벗 아래 종가 {st['below_pivot']}/2번 (2번이면 정리)")
    return "\n".join(t)


# ---------- 19:00 ----------
def _parse_mine(msgs, names):
    """'중기 종목명 수량 [체결가]' / '중기매도 종목명'"""
    add, sold = [], []
    for m in msgs:
        if dt.datetime.fromtimestamp(m["date"], md.KST).strftime("%Y%m%d") != md.today():
            continue
        for line in m.get("text", "").splitlines():
            g = re.match(r"\s*중기매도\s+(\S+)", line)
            if g:
                sold.append(g.group(1)); continue
            g = re.match(r"\s*중기\s+(\S+)\s+(\d+)(?:\s+(\d+))?", line)
            if g:
                key = g.group(1)
                code = key if re.match(r"^\d{6}$", key) else names.get(key)
                if code:
                    add.append(dict(code=code, qty=int(g.group(2)), price=float(g.group(3)) if g.group(3) else None))
    return add, sold


def evening_section(msgs=None):
    os.makedirs(REC, exist_ok=True)
    L = md.all_stocks()
    names = dict(zip(L.name, L.code)); code2name = dict(zip(L.code, L.name))
    lines = ["🟣 중기 스윙 (CAN SLIM)"]
    mst, mtxt = _markets()
    lines.append(mtxt)
    rs = _rs_table(L)

    # 1) 마감 기준 신호 → 모의 기록
    df = _scan(L[L.value >= 10], rs, VOL_MULT)
    log = pd.read_csv(LOG, dtype={"code": str, "date": str}) if os.path.exists(LOG) else pd.DataFrame(
        columns=["date", "code", "name", "grade", "market", "buy", "pivot", "status", "end_date", "why", "ret"])
    held = set(log[log.status == "보유"].code)
    new = []
    if not df.empty:
        for _, r in df[df.breakout].iterrows():
            g = _grade(r.gq, r.ga, mst[r.mkt])
            if g and r.code not in held:
                ok, dl = _dart(r, lines)
                if not ok:
                    continue
                new.append(dict(date=md.today(), code=r.code, name=r["name"], grade=g, market=mst[r.mkt],
                                buy=r.close, pivot=r.pivot, status="보유", end_date="", why="", ret=None))
                lines.append("✅ 오늘 마감 확정 신호\n" + _fmt(r, g) + "\n" + dl)
    if not new:
        lines.append("오늘 마감 확정 신호 없음")
    if new:
        log = pd.concat([log, pd.DataFrame(new)], ignore_index=True)

    # 2) 관심 후보 (피벗 아래 0~5%)
    if not df.empty:
        w = df[(~df.breakout) & (df.gap_pivot >= -5) & (df.gap_pivot <= 0)].copy()
        w["g"] = [_grade(a, b, "켜짐") for a, b in zip(w.gq, w.ga)]
        w = w[w.g.notna()].sort_values("gap_pivot", ascending=False).head(SHOW_WATCH)
        if len(w):
            lines.append("👀 관심 후보 (피벗 돌파 대기)")
            for _, r in w.iterrows():
                lines.append(f"• {r['name']} ({r.code}) {r.close:,.0f}원 → 피벗 {r.pivot:,.0f}원까지 {-r.gap_pivot:.1f}% | 실적 {r.g[0]}등급")

    # 3) 내가 산 중기 종목 관리
    mine = pd.read_csv(MINE, dtype={"code": str, "date": str}) if os.path.exists(MINE) else pd.DataFrame(
        columns=["date", "code", "name", "qty", "buy", "pivot", "status", "end_date", "why", "ret"])
    add, sold = _parse_mine(msgs or [], names)
    for a in add:
        d = _daily(a["code"])
        piv = _base(d)[0] if len(d) > 70 else d.c.iloc[-1]
        prev = log[(log.code == a["code"]) & (log.date == md.today())]
        if len(prev): piv = float(prev.pivot.iloc[0])
        mine = pd.concat([mine, pd.DataFrame([dict(date=md.today(), code=a["code"], name=code2name.get(a["code"], a["code"]),
                                                   qty=a["qty"], buy=a["price"] or d.c.iloc[-1], pivot=piv, status="보유",
                                                   end_date="", why="", ret=None)])], ignore_index=True)
        lines.append(f"📝 중기 매수 기록: {code2name.get(a['code'], a['code'])} {a['qty']}주")
    for key in sold:
        code = key if re.match(r"^\d{6}$", key) else names.get(key)
        mine.loc[(mine.code == code) & (mine.status == "보유"), ["status", "end_date", "why"]] = ["종료", md.today(), "직접 매도"]
    todo = []
    for i, p in mine[mine.status == "보유"].iterrows():
        st = manage(_daily(p.code), p.date, float(p.buy), float(p.pivot))
        if st is None:
            continue
        if st["done"]:
            mine.loc[i, ["status", "end_date", "why", "ret"]] = ["종료", st["date"], st["why"], st["ret"]]
            todo.append(f"• {p['name']} → {st['why']} 조건 ({st['date']}) → 내일 시가 매도 (규칙 기준 {st['ret']:+.1f}%)\n"
                        f"   매도했으면 봇에게: 중기매도 {p['name']}")
            mine.loc[i, "status"] = "보유"  # 직접 '중기매도'를 보내야 종료
        else:
            todo.append(_todo(p["name"], st, float(p.buy), int(p.qty)))
    if todo:
        lines.append("📌 내 중기 종목\n" + "\n".join(todo))

    # 4) 모의 기록 갱신·성적
    for i, p in log[log.status == "보유"].iterrows():
        st = manage(_daily(p.code), p.date, float(p.buy), float(p.pivot))
        if st and st["done"]:
            log.loc[i, ["status", "end_date", "why", "ret"]] = ["종료", st["date"], st["why"], st["ret"]]
    done = log[log.status == "종료"]
    if len(done):
        r = done.ret.astype(float)
        lines.append(f"📒 중기 모의 기록 {len(r)}건 종료 | 승률 {(r > 0).mean() * 100:.0f}% | 평균 {r.mean():+.2f}% | 보유 중 {(log.status == '보유').sum()}건\n"
                     f"   (백테스트 기대: 승률 25~31%, 평균 +3~6%. 3번 중 2번 손절이 정상)")
    log.to_csv(LOG, index=False); mine.to_csv(MINE, index=False)
    return "\n".join(lines)


if __name__ == "__main__":
    import sys
    print(today_signals() if "--1510" in sys.argv else evening_section())
