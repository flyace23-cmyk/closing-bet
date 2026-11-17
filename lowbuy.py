"""저가매수 — 『저가매수의 기술』 엔벨로프 (11년 백테스트: 매매당 승률 75%, 평균 +5.5%, 보유 약 3주)

대상: 관심종목(records/lowbuy_watch.csv)만. 공통: 종가 1,000원 이상, 20일 평균 거래대금 30억 이상
  1차 매수  종가 < 20일선 x 0.9 (보유 중 아님)            → 예산 30%   (+ RSI14 <= 30 이면 '강한 신호')
  2차 매수  종가 <= 1차가 x 0.9, 또는 1차가 아래에서 양봉  → 예산 30%
  3차 매수  종가 <= 2차가 x 0.9                           → 예산 40%
  1차 매도  종가 >= 20일선                                → 보유분 절반, 추가매수 끝
  잔량 매도 1차 매도 뒤 종가 >= 20일선 x 1.1 또는 종가 < 20일선 → 전량
  손절      2차 이상 산 뒤 종가 < 평단 x 0.7                → 전량
  참고      보유 중 5일 지수이평 > 10일 지수이평(골든크로스 유지) → '잔량 더 들고 가도 됨' 문구만

15:10 preview(): 지금 가격으로 오늘 종가에 할 일을 미리 알림
19:00 evening_section(msgs): 확정 종가로 모의 기록(기록장)을 갱신. 텔레그램 '관심추가/관심삭제/관심목록' 처리
판단 순서는 백테스트 엔진(strat_envelope, STOP=0.3)과 같다.
"""
import os, re, json, copy, datetime as dt
import pandas as pd
import market_data as md

HERE = os.path.dirname(os.path.abspath(__file__))
REC = f"{HERE}/records"
WATCH = f"{REC}/lowbuy_watch.csv"      # 관심종목 (code,name)
STATE = f"{REC}/lowbuy_state.json"     # 보유 중 모의 매매와 마지막 처리일
TRADES = f"{REC}/lowbuy_trades.csv"    # 끝난 모의 매매

ENV = 0.10            # 엔벨로프 폭 (20일선 -10%)
STEP = 0.10           # 추가매수 간격 (직전 매수가 -10%)
FRACS = [0.3, 0.3, 0.4]
TOP = 1.10            # 잔량 익절: 20일선 x 1.1
STOP = 0.30           # 안전망: 평단 -30%
MIN_PRICE, MIN_TV20 = 1000, 3e9
COST_BUY, COST_SELL = 0.00015, 0.00015 + 0.0018
BUDGET = 0            # 종목당 예산(원). 0이 아니면 알림에 매수 수량도 표시
NEAR = 5.0            # 하단까지 이 % 이내면 '곧 신호'로 표시
MAX_HOLD = 10         # 종목당 예산 10% → 동시에 최대 10종목


# ---------- 지표 ----------
def indicators(code, n=300):
    d = md.daily(code, n)
    d = d[(d.c > 0) & (d.v > 0)].reset_index(drop=True)
    c = d.c
    d["sma20"] = c.rolling(20).mean()
    d["ema5"] = c.ewm(span=5, adjust=False).mean()
    d["ema10"] = c.ewm(span=10, adjust=False).mean()
    x = c.diff()
    up = x.clip(lower=0).ewm(alpha=1 / 14, adjust=False).mean()
    dn = (-x.clip(upper=0)).ewm(alpha=1 / 14, adjust=False).mean()
    d["rsi"] = 100 - 100 / (1 + up / dn)
    d["tv20"] = (c * d.v).rolling(20).mean()
    return d.iloc[40:].reset_index(drop=True)


def _liquid(r):
    return r.c >= MIN_PRICE and r.tv20 >= MIN_TV20


# ---------- 규칙 (백테스트 strat_envelope 와 같은 순서) ----------
def avg(p):
    b = [(e[2], e[3]) for e in p["ev"] if e[1] == "B"]
    return sum(px * f for px, f in b) / sum(f for _, f in b)


def result(p):
    """비용 뺀 수익률(%) — 아직 남은 수량은 마지막 가격으로 계산"""
    inv = got = sh = 0.0
    for _, t, px, f in p["ev"]:
        if t == "B":
            inv += f * (1 + COST_BUY); sh += f / px
        else:
            q = sh * f; got += q * px * (1 - COST_SELL); sh -= q
    got += sh * p.get("mark", p["ev"][-1][2]) * (1 - COST_SELL)
    return (got / inv - 1) * 100


def step(p, r, code, name):
    """하루 종가 r 로 규칙 적용. (새 상태, 할 일 목록, 끝난 매매)"""
    acts, date = [], r.date
    if p is None:
        if r.c < r.sma20 * (1 - ENV) and _liquid(r):
            p = dict(code=code, name=name, ev=[[date, "B", r.c, FRACS[0]]], buys=1, held=FRACS[0],
                     last=r.c, half=False, strong=bool(r.rsi <= 30))
            acts.append(("1차 매수", FRACS[0]))
        return p, acts, None
    p = copy.deepcopy(p)
    if p["buys"] >= 2 and r.c < avg(p) * (1 - STOP):
        p["ev"].append([date, "S", r.c, 1.0]); p["why"] = "손절"; acts.append(("손절", 1.0))
        return None, acts, p
    if p["buys"] < 3 and not p["half"]:
        if r.c <= p["last"] * (1 - STEP) or (p["buys"] == 1 and r.c > r.o and r.c < p["last"]):
            f = FRACS[p["buys"]]
            p["ev"].append([date, "B", r.c, f]); p["buys"] += 1; p["held"] += f; p["last"] = r.c
            acts.append((f"{p['buys']}차 매수", f))
    if not p["half"] and r.c >= r.sma20:
        p["ev"].append([date, "S", r.c, 0.5]); p["half"] = True; p["held"] *= 0.5
        acts.append(("1차 매도", 0.5))
        return p, acts, None
    if p["half"] and (r.c >= r.sma20 * TOP or r.c < r.sma20):
        p["ev"].append([date, "S", r.c, 1.0]); p["why"] = "20일선+10%" if r.c >= r.sma20 * TOP else "20일선 이탈"
        acts.append(("잔량 매도", 1.0))
        return None, acts, p
    return p, acts, None


# ---------- 기록 파일 ----------
def load_watch():
    if os.path.exists(WATCH):
        return pd.read_csv(WATCH, dtype={"code": str})
    return pd.DataFrame(columns=["code", "name"])


def load_state():
    try:
        return json.load(open(STATE))
    except Exception:
        return dict(upto={}, pos={})


def save_state(s):
    os.makedirs(REC, exist_ok=True)
    json.dump(s, open(STATE, "w"), ensure_ascii=False, indent=1)


# ---------- 문구 ----------
def _won(x):
    return f"{x:,.0f}"


def _qty(price, frac):
    return f" (약 {int(BUDGET * frac // price):,}주)" if BUDGET else ""


def _gc(r):
    return r.ema5 > r.ema10


def fmt_act(kind, frac, p, r, closed=None):
    """문서의 알림 문구 형식"""
    nm = p["name"] if p else closed["name"]
    lo = r.sma20 * (1 - ENV)
    if kind == "1차 매수":
        strong = " (강한 신호)" if r.rsi <= 30 else ""
        return (f"[저가매수] {nm} 1차 매수 신호{strong} | 현재가 {_won(r.c)} / 20일선 -10% {_won(lo)} / RSI {r.rsi:.0f}\n"
                f"   예산 30% 종가 매수{_qty(r.c, frac)} | 2차 조건 {_won(r.c * (1 - STEP))} 이하, 또는 {_won(r.c)} 아래 양봉")
    if kind in ("2차 매수", "3차 매수"):
        nxt = (f" | 3차 조건 {_won(r.c * (1 - STEP))} 이하" if kind == "2차 매수" else "")
        return (f"[저가매수] {nm} {kind} | 현재가 {_won(r.c)} / RSI {r.rsi:.0f}\n"
                f"   예산 {frac * 100:.0f}% 종가 매수{_qty(r.c, frac)}{nxt} | 평단 {_won(avg(p))}, 손절선 {_won(avg(p) * (1 - STOP))}")
    if kind == "1차 매도":
        return (f"[저가매수] {nm} 1차 매도 (20일선 {_won(r.sma20)} 도달) | 현재가 {_won(r.c)}\n"
                f"   보유분 절반 종가 매도, 추가매수 끝 | 잔량: 20일선 x1.1({_won(r.sma20 * TOP)}) 이상 또는 20일선 아래 마감 시 매도")
    if kind == "잔량 매도":
        why = "20일선 +10% 도달" if r.c >= r.sma20 * TOP else "20일선 아래로 마감"
        tip = "\n   참고: 5-10 골든크로스 유지 중 → 잔량 더 들고 가도 됨" if _gc(r) and r.c >= r.sma20 * TOP else ""
        return (f"[저가매수] {nm} 잔량 전부 매도 ({why}) | 현재가 {_won(r.c)} | 이번 매매 약 {result(closed):+.1f}%{tip}")
    if kind == "손절":
        return (f"[저가매수] ⚠️ {nm} 손절 — 평단 {_won(avg(closed))}의 -30% 아래 | 현재가 {_won(r.c)} | 전량 종가 매도 (약 {result(closed):+.1f}%)")
    return f"[저가매수] {nm} {kind}"


def fmt_hold(p, r):
    a = avg(p)
    t = f"• {p['name']} {p['buys']}차까지 매수, 평단 {_won(a)} → 현재 {r.c / a * 100 - 100:+.1f}%"
    if p["half"]:
        t += f" | 절반 매도함. 잔량: {_won(r.sma20 * TOP)} 이상 또는 {_won(r.sma20)} 아래면 매도"
        if _gc(r):
            t += " (5-10 골든 유지: 더 들고 가도 됨)"
    else:
        nxt = []
        if p["buys"] < 3:
            nxt.append(f"{p['buys'] + 1}차 {_won(p['last'] * (1 - STEP))} 이하" + (" 또는 양봉" if p["buys"] == 1 else ""))
        nxt.append(f"20일선 {_won(r.sma20)} 도달 시 절반 매도")
        t += " | 다음: " + ", ".join(nxt)
    return t


def _near(rows):
    """보유 안 한 종목 중 하단에 가까운 것"""
    out = []
    for code, name, r in rows:
        lo = r.sma20 * (1 - ENV)
        gap = (r.c / lo - 1) * 100
        if 0 <= gap <= NEAR:
            out.append((gap, f"{name} 하단까지 {gap:.1f}% (하단 {_won(lo)}, RSI {r.rsi:.0f})"))
    return [x for _, x in sorted(out)[:3]]


def _capacity(held, new):
    if held + new <= MAX_HOLD:
        return []
    room = max(0, MAX_HOLD - held)
    return [f"⚠️ 신규 {new}종목 + 보유 {held}종목 = 종목당 10% 기준 한도({MAX_HOLD}종목) 초과 → 실제로는 {room}종목만. "
            f"'강한 신호'·거래대금 큰 종목부터 고르고, 나머지는 기록만 보세요 (폭락장엔 신호가 몰려요)"]


# ---------- 15:10 ----------
def preview():
    """15:10 알림: 지금 가격 기준으로 오늘 종가에 할 일"""
    W, S = load_watch(), load_state()
    codes = list(dict.fromkeys(list(W.code) + list(S["pos"])))
    names = dict(zip(W.code, W.name))
    acts, holds, free, plan = [], [], [], []
    for code in codes:
        try:
            d = indicators(code)
        except Exception:
            continue
        if d.empty or d.date.iloc[-1] != md.today():
            continue
        r = d.iloc[-1]
        p = S["pos"].get(code)
        name = p["name"] if p else names.get(code, code)
        if code not in names and p is None:
            continue
        np_, a, closed = step(p, r, code, name)
        for k, f in a:
            acts.append(fmt_act(k, f, np_, r, closed))
            plan.append(dict(code=code, name=name, act=k))
        if np_ is not None and not a:
            holds.append(fmt_hold(np_, r))
        if p is None and not a:
            free.append((code, name, r))
    lines = [f"🟢 저가매수 (엔벨로프) — 15:10 예상, 관심 {len(W)}종목"]
    lines += acts if acts else ["오늘 종가에 할 일 없음"]
    if acts:
        lines.append("👉 15:20 이후 가격으로 한 번 더 확인하고 종가(동시호가)에 주문. 종목당 예산은 저가매수 자금의 10%")
        lines += _capacity(len(S["pos"]), sum(1 for x in plan if x["act"] == "1차 매수"))
    if holds:
        lines.append("📌 보유 중 (모의 기록)\n" + "\n".join(holds))
    near = _near(free)
    if near:
        lines.append("👀 곧 신호: " + " / ".join(near))
    os.makedirs(REC, exist_ok=True)
    json.dump(plan, open(f"{REC}/lowbuy_1510_{md.today()}.json", "w"), ensure_ascii=False)
    return "\n".join(lines)


# ---------- 19:00 ----------
def _commands(msgs):
    """'관심추가 종목명' / '관심삭제 종목명' / '관심목록'"""
    cmds = []
    for m in msgs or []:
        if dt.datetime.fromtimestamp(m["date"], md.KST).strftime("%Y%m%d") != md.today():
            continue
        for line in m.get("text", "").splitlines():
            g = re.match(r"\s*관심(추가|삭제)\s+(.+)", line)
            if g:
                cmds += [(g.group(1), k) for k in re.split(r"[\s,]+", g.group(2).strip()) if k]
            elif re.match(r"\s*관심목록", line):
                cmds.append(("목록", ""))
    return cmds


def _apply_commands(cmds, W):
    if not cmds:
        return W, []
    L = md.all_stocks()
    byname, bycode = dict(zip(L.name, L.code)), dict(zip(L.code, L.name))
    out = []
    for op, key in cmds:
        if op == "목록":
            out.append("📋 저가매수 관심종목: " + ", ".join(W.name)); continue
        code = key if re.match(r"^\d{6}$", key) else byname.get(key)
        if not code:
            out.append(f"'{key}' 종목을 못 찾음 (정확한 종목명이나 6자리 코드로 보내 주세요)"); continue
        name = bycode.get(code, key)
        if op == "추가" and code not in set(W.code):
            W = pd.concat([W, pd.DataFrame([dict(code=code, name=name)])], ignore_index=True)
            out.append(f"➕ 관심종목 추가: {name}")
        elif op == "삭제" and code in set(W.code):
            W = W[W.code != code]
            out.append(f"➖ 관심종목 삭제: {name} (보유 중인 모의 매매는 끝까지 관리)")
    W.to_csv(WATCH, index=False)
    return W, out


def evening_section(msgs=None):
    os.makedirs(REC, exist_ok=True)
    W = load_watch()
    W, cmd_lines = _apply_commands(_commands(msgs), W)
    S = load_state()
    names = dict(zip(W.code, W.name))
    codes = list(dict.fromkeys(list(W.code) + list(S["pos"])))
    today_acts, holds, closed_all = [], [], []
    for code in codes:
        try:
            d = indicators(code)
        except Exception:
            continue
        if d.empty:
            continue
        upto = S["upto"].get(code)
        # 처음 보는 종목은 오늘부터 기록 시작. 저녁 정리를 며칠 빠뜨렸으면 그 날들도 차례로 처리
        bars = d[d.date > upto] if upto else d.tail(1)
        p = S["pos"].get(code)
        name = p["name"] if p else names.get(code, code)
        for _, r in bars.iterrows():
            if p is None and code not in names:
                break                      # 관심에서 뺀 종목은 새로 사지 않음
            p, a, closed = step(p, r, code, name)
            for k, f in a:
                if r.date == md.today():
                    today_acts.append((code, k, fmt_act(k, f, p, r, closed)))
            if closed:
                closed["mark"] = closed["ev"][-1][2]
                closed_all.append(closed)
        S["upto"][code] = d.date.iloc[-1]
        if p is None:
            S["pos"].pop(code, None)
        else:
            S["pos"][code] = p
            if not any(c == code for c, _, _ in today_acts):
                holds.append(fmt_hold(p, d.iloc[-1]))
        names.setdefault(code, name)
    # 끝난 매매 저장
    if closed_all:
        rows = [dict(code=c["code"], name=c["name"], entry=c["ev"][0][0], exit=c["ev"][-1][0], buys=c["buys"],
                     strong=c.get("strong", False), why=c.get("why", ""),
                     ret=round(result(c), 2)) for c in closed_all]
        old = pd.read_csv(TRADES, dtype={"code": str, "entry": str, "exit": str}) if os.path.exists(TRADES) else pd.DataFrame()
        pd.concat([old, pd.DataFrame(rows)], ignore_index=True).to_csv(TRADES, index=False)
    save_state(S)

    lines = ["🟢 저가매수 (엔벨로프) — 오늘 종가 확정"]
    lines += cmd_lines
    lines += [t for _, _, t in today_acts] if today_acts else ["오늘 확정 신호 없음"]
    new1 = sum(1 for _, k, _ in today_acts if k == "1차 매수")
    lines += _capacity(len(S["pos"]) - new1, new1)
    # 15:10 예상과 다른 것
    f = f"{REC}/lowbuy_1510_{md.today()}.json"
    if os.path.exists(f):
        early = {(x["code"], x["act"]) for x in json.load(open(f))}
        final = {(c, k) for c, k, _ in today_acts}
        diff = [f"{names.get(c, c)} {k} {'(15:10엔 있었는데 종가 기준으론 아님)' if (c, k) in early else '(종가에 새로 생김)'}" for c, k in early ^ final]
        if diff:
            lines.append("🔎 15:10 예상과 다름: " + ", ".join(diff))
    if holds:
        lines.append("📌 보유 중 (모의 기록)\n" + "\n".join(holds))
    if os.path.exists(TRADES):
        t = pd.read_csv(TRADES)
        if len(t):
            lines.append(f"📒 저가매수 모의 기록 {len(t)}건 종료 | 승률 {(t.ret > 0).mean() * 100:.0f}% | 평균 {t.ret.mean():+.2f}% "
                         f"(비용 뺌)\n   백테스트 기대: 승률 75%, 평균 +5.5%, 보유 약 3주")
    lines.append("💬 관심종목 바꾸기: 봇에게 '관심추가 종목명' / '관심삭제 종목명' / '관심목록' (저녁 정리 때 반영)")
    return "\n".join(lines)


if __name__ == "__main__":
    import sys
    print(preview() if "--1510" in sys.argv else evening_section())
