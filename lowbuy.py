"""저가매수 — 『저가매수의 기술』 엔벨로프 (11년 백테스트: 매매당 승률 75%, 평균 +5.5%, 보유 약 3주)

대상: 코스피·코스닥 시총 상위 각 200개 보통주 (봇이 매주 자동 갱신) + '관심추가' 종목 - '관심삭제' 종목
공통: 종가 1,000원 이상, 20일 평균 거래대금 30억 이상
  1차 매수  종가 < 20일선 x 0.9 (보유 중 아님)            → 예산 30%   (+ RSI14 <= 30 이면 '강한 신호')
  2차 매수  종가 <= 1차가 x 0.9, 또는 1차가 아래에서 양봉  → 예산 30%
  3차 매수  종가 <= 2차가 x 0.9                           → 예산 40%
  1차 매도  종가 >= 20일선                                → 보유분 절반, 추가매수 끝
  잔량 매도 1차 매도 뒤 종가 >= 20일선 x 1.1 또는 종가 < 20일선 → 전량
  손절      2차 이상 산 뒤 종가 < 평단 x 0.7                → 전량
  참고      보유 중 5일 지수이평 > 10일 지수이평(골든크로스 유지) → '잔량 더 들고 가도 됨' 문구만

자금: 5칸 (종목당 저가매수 자금의 20%). 칸이 비어 있을 때만 새 1차 신호를 채움
  채우는 순서: 테마가 같이 빠진 종목 먼저 → 혼자 빠진 종목, 그 안에서 거래대금 큰 순
  근거: 프로젝트 문서 '저가매수-종목고르기-집중투자-검증-2026-11'
    - 5칸이 1·2·10칸보다 나았음 (연 7.4%, 최대 낙폭 -40%)
    - 혼자 빠진 종목(테마 20% 미만만 같이 빠짐)은 매매당 +3.7%, 테마가 같이 빠진 종목은 +7.0%
      → 혼자 빠진 종목엔 뉴스·공시를 붙여 개별 악재인지 확인
기록: 모든 신호(전체 기록)와 5칸(내 기록)을 따로 저장

15:10 preview(): 지금 가격으로 오늘 종가에 할 일을 미리 알림
19:00 evening_section(msgs): 확정 종가로 기록 갱신, 5칸 채우기. 텔레그램 '관심추가/관심삭제/관심목록' 처리
판단 순서는 백테스트 엔진(strat_envelope, STOP=0.3)과 같다.
"""
import os, re, json, copy, datetime as dt
from concurrent.futures import ThreadPoolExecutor
import pandas as pd
import market_data as md

HERE = os.path.dirname(os.path.abspath(__file__))
REC = f"{HERE}/records"
EXTRA = f"{REC}/lowbuy_extra.csv"      # 관심추가한 종목 (code,name)
EXCL = f"{REC}/lowbuy_exclude.csv"     # 관심삭제한 종목 (code,name)
STATE = f"{REC}/lowbuy_state.json"     # 진행 중 모의 매매, 5칸, 마지막 처리일
TRADES = f"{REC}/lowbuy_trades.csv"    # 끝난 모의 매매 (slot=True 이면 5칸 매매)

ENV = 0.10            # 엔벨로프 폭 (20일선 -10%)
STEP = 0.10           # 추가매수 간격 (직전 매수가 -10%)
FRACS = [0.3, 0.3, 0.4]
TOP = 1.10            # 잔량 익절: 20일선 x 1.1
STOP = 0.30           # 안전망: 평단 -30%
MIN_PRICE, MIN_TV20 = 1000, 3e9
COST_BUY, COST_SELL = 0.00015, 0.00015 + 0.0018
SLOTS = 5             # 동시에 들고 갈 종목 수 (종목당 저가매수 자금의 20%)
UNI_TOP = 200         # 시장별 시총 상위 몇 개를 볼지
SOLO = 0.2            # 같은 테마 중 하단 아래 비율이 이보다 낮으면 '혼자 빠짐'
BUDGET = 0            # 종목당 예산(원). 0이 아니면 알림에 매수 수량도 표시
SHOW_OTHERS = 10      # 칸에 못 들어간 신호 중 이름을 보여줄 개수
ACTS = ["1차 매수", "2차 매수", "3차 매수", "1차 매도", "잔량 매도", "손절"]


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
    d["r120"] = c / c.shift(120) - 1
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


# ---------- 대상 종목 ----------
def _list(f):
    if os.path.exists(f):
        return pd.read_csv(f, dtype={"code": str})
    return pd.DataFrame(columns=["code", "name"])


def _top_stocks():
    """시장별 시총 상위 UNI_TOP개 보통주 (스팩·리츠·우선주 제외)"""
    out = []
    for mkt in ["KOSPI", "KOSDAQ"]:
        n = 0
        for page in range(1, 10):
            st = md.S.get(f"https://m.stock.naver.com/api/stocks/marketValue/{mkt}?page={page}&pageSize=50", timeout=15).json().get("stocks", [])
            if not st:
                break
            for s in st:
                if n >= UNI_TOP:
                    break
                if s.get("stockEndType") != "stock" or not re.match(r"^\d{5}0$", s["itemCode"]) or re.search("스팩|리츠", s["stockName"]):
                    continue
                out.append([s["itemCode"], s["stockName"]]); n += 1
            if n >= UNI_TOP:
                break
    return out


def universe():
    """{code: name}. 시총 목록은 일주일에 한 번 새로 받음"""
    import info
    top = info._cache_get("lowbuy_universe.json", 7)
    if not top:
        top = _top_stocks()
        info._cache_put("lowbuy_universe.json", top)
    U = {c: n for c, n in top}
    E = _list(EXTRA)
    U.update(dict(zip(E.code, E.name)))
    for c in _list(EXCL).code:
        U.pop(c, None)
    return U


def _fetch(codes):
    def one(c):
        try:
            return c, indicators(c)
        except Exception:
            return c, None
    with ThreadPoolExecutor(8) as ex:
        return {c: d for c, d in ex.map(one, codes) if d is not None and not d.empty}


# ---------- 테마 표시 ----------
def _theme_map(U):
    """code → 그 종목이 속한 테마들의 (대상 종목만 남긴) 구성 목록"""
    try:
        import info
        T = info._themes()
    except Exception:
        return {}
    m = {}
    for t in T:
        mem = [c for c in t["codes"] if c in U]
        if len(mem) >= 3:
            for c in mem:
                m.setdefault(c, []).append((t["name"], mem))
    return m


def label(code, D, TM):
    """dict(solo, codip, lead, text): 테마가 같이 빠졌는지, 테마 주도주인지"""
    th = TM.get(code, [])
    best, lead, lead_name = (-1, ""), False, ""
    for nm, mem in th:
        rows = {c: D[c].iloc[-1] for c in mem if c in D}
        if not rows:
            continue
        below = sum(1 for r in rows.values() if r.c < r.sma20 * (1 - ENV)) / len(rows)
        if below > best[0]:
            best = (below, nm)
        rr = {c: r.r120 for c, r in rows.items() if r.r120 == r.r120}
        if rr and max(rr, key=rr.get) == code:
            lead, lead_name = True, nm
    if best[0] < 0:
        return dict(solo=False, codip=None, lead=False, text="테마 정보 없음")
    solo = best[0] < SOLO
    txt = (f"테마 '{best[1]}' {best[0] * 100:.0f}% 같이 빠짐" if not solo
           else f"⚠️ 혼자 빠짐 (테마 '{best[1]}' {best[0] * 100:.0f}%만 하단 아래)")
    if lead:
        txt += f" | 테마 주도주('{lead_name}' 120일 상승 1등)"
    return dict(solo=solo, codip=best[0], lead=lead, text=txt)


def _detail(code, lab):
    """혼자 빠진 종목에는 뉴스·공시를 붙임"""
    if not lab["solo"]:
        return ""
    try:
        import info
        return "\n" + info.news_line(code) + "\n" + info.dart_safe_line(code)
    except Exception:
        return ""


def _pick(cands, D, TM, room):
    """오늘 새 1차 신호 중 빈 칸에 넣을 종목. (뽑힌 것, 나머지) — 각 [(code, label)]"""
    labs = {c: label(c, D, TM) for c in cands}
    order = sorted(cands, key=lambda c: (labs[c]["solo"], -D[c].iloc[-1].tv20))
    room = max(0, room)
    return [(c, labs[c]) for c in order[:room]], [(c, labs[c]) for c in order[room:]]


# ---------- 기록 파일 ----------
def load_state():
    try:
        s = json.load(open(STATE))
    except Exception:
        s = {}
    s.setdefault("upto", {}); s.setdefault("pos", {}); s.setdefault("slots", [])
    return s


def save_state(s):
    os.makedirs(REC, exist_ok=True)
    json.dump(s, open(STATE, "w"), ensure_ascii=False, indent=1)



# ---------- 문구 (할 일별로 묶고 종목당 한 줄) ----------
def _won(x):
    return f"{x:,.0f}"


def _gc(r):
    return r.ema5 > r.ema10


def _marks(r, lab):
    m = ""
    if r.rsi <= 30:
        m += " 💪"
    if lab and lab.get("lead"):
        m += " ★"
    if lab and lab.get("solo"):
        m += " ⚠️"
    return m


def _qty(price, frac):
    return f" 약 {int(BUDGET * frac // price):,}주" if BUDGET else ""


def act_lists(items):
    """items: [(code, kind, frac, name, r, p_or_closed, lab)] → 문구 줄 목록 (할 일별 묶음)"""
    new = [x for x in items if x[1] == "1차 매수"]
    add = [x for x in items if x[1] in ("2차 매수", "3차 매수")]
    sell = [x for x in items if x[1] in ("1차 매도", "잔량 매도")]
    stop = [x for x in items if x[1] == "손절"]
    out = []
    if new:
        out.append("🛒 새로 사기 (종가, 칸 예산의 30%)")
        out += [f"{i}. {nm} {_won(r.c)}{_qty(r.c, f)}{_marks(r, lab)}" for i, (_, _, f, nm, r, _, lab) in enumerate(new, 1)]
    if add:
        out.append("➕ 더 사기 (종가)")
        out += [f"• {nm} {k} {_won(r.c)} (칸 예산의 {f * 100:.0f}%){_qty(r.c, f)}" for _, k, f, nm, r, _, _ in add]
    if sell:
        out.append("💰 팔기 (종가)")
        for _, k, f, nm, r, p, _ in sell:
            if k == "1차 매도":
                out.append(f"• {nm} 절반 매도 {_won(r.c)} (20일선 도달)")
            else:
                why = "20일선 +10%" if r.c >= r.sma20 * TOP else "20일선 아래로 마감"
                tip = " — 5-10 골든 유지 중이라 더 들고 가도 됨" if _gc(r) and r.c >= r.sma20 * TOP else ""
                out.append(f"• {nm} 남은 것 전부 매도 {_won(r.c)} ({why}, 이번 매매 약 {result(p):+.1f}%){tip}")
    if stop:
        out.append("🛑 손절 (종가, 전부)")
        out += [f"• {nm} {_won(r.c)} (평단 {_won(avg(p))}의 -30% 아래, 약 {result(p):+.1f}%)" for _, _, _, nm, r, p, _ in stop]
    if (new and not (add or sell or stop)):
        out.append("💰 팔기 · ➕ 더 사기 · 🛑 손절: 없음")
    return out


def solo_details(items):
    """⚠️ 혼자 빠진 새 종목만 뉴스·공시"""
    out = []
    for code, k, _, nm, _, _, lab in items:
        if k == "1차 매수" and lab and lab.get("solo"):
            out.append(f"⚠️ {nm} — {lab['text'].replace('⚠️ ', '')}" + _detail(code, lab))
    if out:
        out.append("→ 개별 악재면 건너뛰기 (11년 평균: 혼자 빠짐 +3.7% / 같이 빠짐 +7.0%). Claude에게 '해석해줘'로 보내도 돼요")
    return out


def legend(items):
    labs = [x[6] for x in items if x[6]]
    rs = [x[4] for x in items]
    t = []
    if any(r.rsi <= 30 for r in rs):
        t.append("💪 강한 신호(RSI 30↓)")
    if any(l.get("lead") for l in labs):
        t.append("★ 테마 주도주")
    if any(l.get("solo") for l in labs):
        t.append("⚠️ 혼자 빠짐")
    return "  ".join(t)


def watch_line(p, r):
    """저녁용: 칸별 내일 볼 가격"""
    a = avg(p)
    t = f"• {p['name']} {p['buys']}차까지 | 평단 {_won(a)} ({r.c / a * 100 - 100:+.1f}%) | "
    if p["half"]:
        t += f"남은 것: {_won(r.sma20 * TOP)}↑ 또는 {_won(r.sma20)}↓ 마감이면 매도"
        if _gc(r):
            t += " (골든 유지)"
    else:
        nxt = []
        if p["buys"] < 3:
            nxt.append(f"더 사기 {_won(p['last'] * (1 - STEP))}↓" + (" 또는 양봉" if p["buys"] == 1 else ""))
        nxt.append(f"절반 매도 {_won(r.sma20)}↑")
        if p["buys"] >= 2:
            nxt.append(f"손절 {_won(a * (1 - STOP))}↓")
        t += " · ".join(nxt)
    return t


def _names_line(rest, names, n=SHOW_OTHERS):
    if not rest:
        return ""
    shown = ", ".join(names.get(c, c) + ("★" if l["lead"] else "") + ("⚠️" if l["solo"] else "") for c, l in rest[:n])
    more = f" 외 {len(rest) - n}개" if len(rest) > n else ""
    return f"ℹ️ 칸이 없어 기록만 한 신호 {len(rest)}개: {shown}{more}"


# ---------- 15:10 ----------
def preview():
    """15:10 알림: 지금 가격 기준으로 오늘 종가에 할 일"""
    U, S = universe(), load_state()
    names = {**U, **{c: p["name"] for c, p in S["pos"].items()}}
    D = {c: d for c, d in _fetch(list(dict.fromkeys(list(U) + list(S["pos"])))).items() if d.date.iloc[-1] == md.today()}
    if not D:
        return "🟢 저가매수 15:10 — 오늘 데이터를 못 받음"
    items, new, plan = [], [], []
    held, open_after = len(S["slots"]), len(S["slots"])
    for code, d in D.items():
        r = d.iloc[-1]
        p = S["pos"].get(code)
        if p is None and code not in U:
            continue
        np_, a, closed = step(p, r, code, names.get(code, code))
        if code in S["slots"]:
            items += [(code, k, f, names.get(code, code), r, closed or np_, None) for k, f in a]
            if np_ is None:
                open_after -= 1
        elif p is None and a:
            new.append(code)
    picks, rest = _pick(new, D, _theme_map(U), SLOTS - open_after)
    items += [(c, "1차 매수", FRACS[0], names[c], D[c].iloc[-1], None, lab) for c, lab in picks]
    plan = [dict(code=x[0], act=x[1]) for x in items]
    lines = [f"🟢 저가매수 15:10 — 오늘 할 일 {len(items)}건",
             f"내 {SLOTS}칸: 보유 {held}" + (f" → 오늘 {len(picks)}칸 새로 채움" if picks else "")]
    if items:
        lines += [""] + act_lists(items)
    else:
        lines.append("오늘 종가에 할 일 없음")
    sd = solo_details(items)
    if sd:
        lines += [""] + sd
    lines.append("")
    if rest:
        lines.append(f"ℹ️ 그 밖에 신호 {len(rest)}개는 기록만 (저녁에 이름 확인)")
    if items:
        lines.append("👉 15:20 이후 다시 보고 종가에 주문")
    lg = legend(items)
    if lg:
        lines.append(lg)
    os.makedirs(REC, exist_ok=True)
    json.dump(plan, open(f"{REC}/lowbuy_1510_{md.today()}.json", "w"), ensure_ascii=False)
    return "\n".join(lines).strip()


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


def _apply_commands(cmds):
    if not cmds:
        return []
    L = md.all_stocks()
    byname, bycode = dict(zip(L.name, L.code)), dict(zip(L.code, L.name))
    E, X = _list(EXTRA), _list(EXCL)
    out = []
    for op, key in cmds:
        if op == "목록":
            out.append(f"📋 저가매수 대상: 시총 상위 각 {UNI_TOP}개 자동"
                       + (f" + 추가 {', '.join(E.name)}" if len(E) else "") + (f" - 제외 {', '.join(X.name)}" if len(X) else ""))
            continue
        code = key if re.match(r"^\d{6}$", key) else byname.get(key)
        if not code:
            out.append(f"'{key}' 종목을 못 찾음 (정확한 종목명이나 6자리 코드로 보내 주세요)"); continue
        name = bycode.get(code, key)
        row = pd.DataFrame([dict(code=code, name=name)])
        if op == "추가":
            X = X[X.code != code]
            if code not in set(E.code):
                E = pd.concat([E, row], ignore_index=True)
            out.append(f"➕ 저가매수 대상 추가: {name}")
        else:
            E = E[E.code != code]
            if code not in set(X.code):
                X = pd.concat([X, row], ignore_index=True)
            out.append(f"➖ 저가매수 대상에서 제외: {name} (진행 중인 매매는 끝까지 관리)")
    os.makedirs(REC, exist_ok=True)
    E.to_csv(EXTRA, index=False); X.to_csv(EXCL, index=False)
    return out


def _stats(t, title, exp=""):
    if t.empty:
        return ""
    return f"{title} {len(t)}건 종료 | 승률 {(t.ret > 0).mean() * 100:.0f}% | 평균 {t.ret.mean():+.2f}% {exp}".rstrip()

def evening_section(msgs=None):
    os.makedirs(REC, exist_ok=True)
    cmd_lines = _apply_commands(_commands(msgs))
    U, S = universe(), load_state()
    names = {**U, **{c: p["name"] for c, p in S["pos"].items()}}
    D = _fetch(list(dict.fromkeys(list(U) + list(S["pos"]))))
    items, new_today, closed_all = [], [], []
    for code, d in D.items():
        upto = S["upto"].get(code)
        # 처음 보는 종목은 오늘부터 기록 시작. 저녁 정리를 며칠 빠뜨렸으면 그 날들도 차례로 처리
        bars = d[d.date > upto] if upto else d.tail(1)
        p = S["pos"].get(code)
        name = names.get(code, code)
        for _, r in bars.iterrows():
            if p is None and code not in U:
                break                      # 대상에서 빠진 종목은 새로 사지 않음
            p0 = p
            p, a, closed = step(p, r, code, name)
            if r.date == md.today():
                if p0 is None and a:
                    new_today.append(code)
                elif code in S["slots"]:
                    items += [(code, k, f, name, r, closed or p, None) for k, f in a]
            if closed:
                closed["mark"] = closed["ev"][-1][2]
                closed["slot"] = code in S["slots"]
                closed_all.append(closed)
                if code in S["slots"]:
                    S["slots"].remove(code)
        S["upto"][code] = d.date.iloc[-1]
        if p is None:
            S["pos"].pop(code, None)
        else:
            S["pos"][code] = p
    S["slots"] = [c for c in S["slots"] if c in S["pos"]]
    # 빈 칸 채우기 (오늘 새로 뜬 1차 신호에서)
    today = {c: D[c] for c in D if D[c].date.iloc[-1] == md.today()}
    picks, rest = _pick([c for c in new_today if c in today], today, _theme_map(U), SLOTS - len(S["slots"]))
    for c, lab in picks:
        S["slots"].append(c)
        items.append((c, "1차 매수", FRACS[0], names.get(c, c), D[c].iloc[-1], S["pos"][c], lab))
    # 끝난 매매 저장
    if closed_all:
        rows = [dict(code=c["code"], name=c["name"], entry=c["ev"][0][0], exit=c["ev"][-1][0], buys=c["buys"],
                     strong=c.get("strong", False), slot=c.get("slot", False), why=c.get("why", ""),
                     ret=round(result(c), 2)) for c in closed_all]
        old = pd.read_csv(TRADES, dtype={"code": str, "entry": str, "exit": str}) if os.path.exists(TRADES) else pd.DataFrame()
        pd.concat([old, pd.DataFrame(rows)], ignore_index=True).to_csv(TRADES, index=False)
    save_state(S)

    lines = [f"🟢 저가매수 19:00 — 오늘 종가 확정 {len(items)}건"] + cmd_lines
    if items:
        lines += [""] + act_lists(items)
    else:
        lines.append("오늘 확정된 할 일 없음")
    sd = solo_details(items)
    if sd:
        lines += [""] + sd
    f = f"{REC}/lowbuy_1510_{md.today()}.json"
    if os.path.exists(f):
        early = {(x["code"], x["act"]) for x in json.load(open(f))}
        final = {(x[0], x[1]) for x in items}
        diff = [f"{names.get(c, c)} {k} {'(15:10엔 있었는데 종가 기준으론 아님)' if (c, k) in early else '(종가에 새로 생김)'}"
                for c, k in sorted(early ^ final)]
        if diff:
            lines += ["", "🔎 15:10 예상과 다름: " + ", ".join(diff)]
    if S["slots"]:
        lines += ["", f"📌 내 {SLOTS}칸 · 내일 볼 가격 ({len(S['slots'])}/{SLOTS})"]
        lines += [watch_line(S["pos"][c], D[c].iloc[-1]) for c in S["slots"] if c in D]
    nl = _names_line(rest, names)
    if nl:
        lines += ["", nl]
    stats = []
    if os.path.exists(TRADES):
        t = pd.read_csv(TRADES)
        stats = [x for x in [_stats(t[t.slot == True], f"📒 내 {SLOTS}칸 기록"),
                             _stats(t, "📒 전체 신호 기록", "(기대: 승률 75%, 평균 +5.5%)")] if x]
    lines += [""] + stats + [f"진행 중: 내 칸 {len(S['slots'])}/{SLOTS}, 전체 신호 {len(S['pos'])}개"]
    lg = legend(items)
    if lg:
        lines.append(lg)
    lines.append("💬 대상 바꾸기: '관심추가 종목명' / '관심삭제 종목명' / '관심목록'")
    return "\n".join(lines).strip()


if __name__ == "__main__":
    import sys
    print(preview() if "--1510" in sys.argv else evening_section())
