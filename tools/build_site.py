"""알림장 웹페이지 만들기 (GitHub Pages: docs 폴더)

  index.html        첫 화면: 매매법별 누적 성적(단계별, 한 줄씩), 진행 중 종목(한 줄씩), 알림 달력, 최근 알림
  market.html       대장주 달력: 날짜마다 코스피·코스닥 등락과 1등 테마
  d/날짜.html       하루치 알림: 보낸 알림 원문(봇 + 노트북 VI봇), 대장주, VI 복기, 15분봉 단타 모의, 끝난 매매
  m/날짜.html       하루치 시장: 지수, 오른·내린 종목 수, 테마별 상승률, 대장주(테마 색)
  flow.html         장중 흐름 (가장 최근 날, ?d=날짜 로 다른 날)
  live.js           데스크톱 모의주문봇이 올린 docs/live/*.json(모의 계좌·지표·30분 장중 흐름)을 페이지에서 바로 그림
  w/월요일.html     주간 복기: 단계별 성적, 대장주 다음날 성적, 모의매매 집계

사용: python tools/build_site.py
"""
import os, sys, json, glob, html, hashlib, calendar, datetime as dt
import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
REC = os.path.join(ROOT, "records")
VI = os.path.join(REC, "vi")
OUT = os.path.join(ROOT, "docs")
LIVE = os.path.join(OUT, "live")   # 데스크톱 봇이 GitHub에 직접 올림 (페이지 다시 만들 필요 없음)
WD = "월화수목금토일"
M15 = "15분봉 MACD·일목 단타"

# 단계: 보유 기간으로 나눔
STAGE = {"VI 단타": "초단타", M15: "초단타", "종가베팅": "단타", "저가매수": "스윙", "스윙 A": "스윙", "중기 스윙": "중기 스윙"}
STAGE_ORDER = ["초단타", "단타", "스윙", "중기 스윙"]
STAGE_NOTE = {"초단타": "장중", "단타": "하룻밤", "스윙": "며칠~몇 주", "중기 스윙": "몇 주~몇 달"}
SHOW_NAME = {"중기 스윙": "CAN SLIM"}
EXPECT_M15 = (27, -0.41)   # 1년 검증 (15분봉, 288종목)
STATUS = {"종가베팅": "검증 통과 (11년)", "중기 스윙": "검증 통과 (20년)", "저가매수": "검증 통과 · 모의 확인 중",
          "스윙 A": "검증 통과 (12년)", "VI 단타": "테스트 중", M15: "테스트 중 (1년 검증 미통과)"}
PALETTE = ["#e3120b", "#2e6f8e", "#e8a317", "#3c8d5a", "#8e44ad", "#d35400", "#16a085", "#c0398b", "#5b6ee1", "#7f8c2d", "#b5651d", "#0f8fbf"]


def E(x):
    return html.escape("" if x is None or (isinstance(x, float) and x != x) else str(x), quote=False)


def ymd(d):
    return f"{d[:4]}-{d[4:6]}-{d[6:]}"


def fmt_d(d, wd=True):
    x = dt.datetime.strptime(d, "%Y%m%d")
    return f"{x.month}월 {x.day}일" + (f"({WD[x.weekday()]})" if wd else "")


def monday(d):
    x = dt.datetime.strptime(d, "%Y%m%d")
    return (x - dt.timedelta(days=x.weekday())).strftime("%Y%m%d")


def fnum(v):
    try:
        v = float(v)
        return None if v != v else v
    except (TypeError, ValueError):
        return None


def num(v, nd=2, unit="%"):
    v = fnum(v)
    if v is None:
        return "–"
    cls = "up" if v > 0 else "dn" if v < 0 else ""
    return f'<span class="{cls}">{v:+.{nd}f}{unit}</span>'


def color(theme):
    if not theme:
        return "#8a959c"
    return PALETTE[int(hashlib.md5(theme.encode()).hexdigest(), 16) % len(PALETTE)]


def chip(theme, short=True):
    if not theme:
        return ""
    t = short_theme(theme) if short else theme.split("(")[0].strip()
    return f'<span class="chip" style="--c:{color(theme)}" title="{E(theme)}">{E(t)}</span>'


def read(path):
    return pd.read_csv(path, dtype={"code": str, "date": str, "종목코드": str, "코드": str, "날짜": str, "시작일": str}) if os.path.exists(path) and os.path.getsize(path) else pd.DataFrame()


def wide(head, rows, right=()):
    """옆으로 쭉 이어지는 표 (휴대폰에서는 옆으로 밀어서 봄, 첫 칸은 고정)"""
    if not rows:
        return '<p class="empty">기록 없음</p>'
    th = "".join(f'<th class="{"r" if i in right else ""}">{h}</th>' for i, h in enumerate(head))
    tb = ""
    for r in rows:
        cls, cells = r if isinstance(r, tuple) else ("", r)
        if cls == "group":
            tb += f'<tr class="group"><td colspan="{len(head)}">{cells}</td></tr>'
            continue
        tb += f'<tr class="{cls}">' + "".join(f'<td class="{"r" if i in right else ""}">{c}</td>' for i, c in enumerate(cells)) + "</tr>"
    return f'<div class="scroll"><table class="wide"><thead><tr>{th}</tr></thead><tbody>{tb}</tbody></table></div>'


def extra(r):
    """손익비(이길 때 평균 ÷ 질 때 평균), 최대 연패, 최대 낙폭(누적 합계 기준)"""
    r = pd.to_numeric(pd.Series(r, dtype=object), errors="coerce").dropna().tolist()
    if not r:
        return ""
    w = [x for x in r if x > 0]; l = [-x for x in r if x <= 0]
    pr = f"{(sum(w) / len(w)) / (sum(l) / len(l)):.1f}" if w and l else ("–" if not w else "∞")
    streak = mx = 0
    for x in r:
        streak = streak + 1 if x <= 0 else 0; mx = max(mx, streak)
    cum = peak = dd = 0
    for x in r:
        cum += x; peak = max(peak, cum); dd = min(dd, cum - peak)
    return f"손익비 {pr} · 최대 연패 {mx} · 최대 낙폭 {dd:.1f}%"


def stat(r):
    r = pd.to_numeric(pd.Series(r, dtype=object), errors="coerce").dropna()
    if not len(r):
        return 0, None, None
    return len(r), (r > 0).mean() * 100, r.mean()


# ---------- 데이터 ----------
def messages(d):
    out = []
    for f, src in ((os.path.join(REC, "messages", f"{d}.jsonl"), "봇"), (os.path.join(VI, "messages", f"{d}.jsonl"), "VI")):
        if os.path.exists(f):
            for line in open(f, encoding="utf-8"):
                try:
                    m = json.loads(line); m["src"] = m.get("src") or src; out.append(m)
                except Exception:
                    pass
    return sorted(out, key=lambda m: m["t"])


_MK = {}


def market(d):
    if d not in _MK:
        try:
            _MK[d] = json.load(open(os.path.join(REC, "market", f"{d}.json"), encoding="utf-8"))
        except Exception:
            _MK[d] = None
    return _MK[d]


def load():
    try:
        sys.path.insert(0, os.path.join(ROOT, "tools"))
        import build_dashboard as bd
        t, s, h = bd.collect(VI if os.path.isdir(VI) else None)
        expect = bd.EXPECT
    except Exception as e:
        print("성적 모으기 실패:", e)
        t, h, expect = pd.DataFrame(columns=["매매법", "구분", "종목", "산 날", "판 날", "수익률(%)", "메모"]), pd.DataFrame(), {}
    fm = read(os.path.join(REC, "father_mock.csv"))
    if len(fm):
        fm["ret"] = pd.to_numeric(fm.ret)
    lead = read(os.path.join(REC, "leaders.csv"))
    vi = read(os.path.join(VI, "review.csv"))
    if len(vi):
        vi["date"] = vi["날짜"].str.replace("-", "")
    return t, h, fm, lead, vi, expect


def all_dates(t, fm, lead, vi):
    ds = set()
    for f in glob.glob(os.path.join(REC, "messages", "*.jsonl")) + glob.glob(os.path.join(VI, "messages", "*.jsonl")) + glob.glob(os.path.join(REC, "market", "*.json")) + glob.glob(os.path.join(LIVE, "2*.json")):
        ds.add(os.path.basename(f)[:8])
    for df in (fm, lead, vi):
        if len(df):
            ds |= set(df.date)
    if len(t):
        ds |= {str(x).replace("-", "") for x in t["판 날"].dropna() if x}
    return sorted((d for d in ds if len(d) == 8 and d.isdigit() and dt.datetime.strptime(d, "%Y%m%d").weekday() < 5), reverse=True)


def theme_of(r, mk):
    th = getattr(r, "main_theme", None)
    if isinstance(th, str) and th:
        return th
    if mk:
        for x in mk.get("leaders", []):
            if x.get("code") == r.code and x.get("theme"):
                return x["theme"]
    ths = getattr(r, "themes", "")
    return ths.split("|")[0] if isinstance(ths, str) and ths else ""


# ---------- 조각 ----------
# 매매법 한 줄씩: (매매법 키, 보이는 이름, 대표 구분 후보 순서). 진행 중 탭과 같은 이름·같은 순서
STRATS = [("VI 단타", "VI 단타", ["자동 복기(정식 시간)", "봇 신호"]),
          (M15, M15, ["모의"]),
          ("종가베팅", "종가베팅", ["실제", "모의(알려준 후보)"]),
          ("저가매수", "저가매수", ["내 5칸", "전체 신호"]),
          ("스윙 A", "스윙 A", ["모의"]),
          ("중기 스윙", "CAN SLIM", ["실제", "모의"])]


def strat_rows(t, expect, with_expect=True, h=None):
    """매매법마다 한 줄. 큰 숫자는 대표 구분(실제가 있으면 실제), 나머지 구분은 작은 글씨. 진행 중 종목 수와 탭 연결"""
    base = h["매매법"].astype(str).str.split("(").str[0] if h is not None and len(h) else pd.Series(dtype=str)
    tab_idx = {k: i for i, (k, _, _) in enumerate(HOLD_TABS)}
    rows, last = [], None
    for key, label, kinds in STRATS:
        g_all = t[t.매매법 == key] if len(t) else t
        main = next((k for k in kinds if len(g_all) and (g_all.구분 == k).any()), next((k for k in kinds if k != "실제"), kinds[0]))
        g = g_all[g_all.구분 == main] if len(g_all) else g_all
        n, w, a = stat(g["수익률(%)"] if len(g) else [])
        e = expect.get((key, main)) or (EXPECT_M15 if key == M15 else (None, None))
        st = STATUS.get(key, "")
        badge = f'<span class="badge {"test" if st.startswith("테스트") else "ok"}">{E(st.split(" (")[0].split(" ·")[0])}</span>' if st else ""
        stage = STAGE[key]
        if stage != last:
            rows.append(("group", f"<b>{stage}</b> <small>{STAGE_NOTE[stage]}</small>"))
            last = stage
        others = []
        for k2, g2 in (g_all.groupby("구분") if len(g_all) else []):
            if k2 != main:
                n2, w2, a2 = stat(g2["수익률(%)"])
                others.append(f"{E(k2)} {n2}건 {num(a2)}")
        hold_n = int((base == key).sum()) if len(base) else 0
        link = (f'<a class="go" href="#hp-{tab_idx[key]}">진행 중 {hold_n}종목 ›</a>' if key in tab_idx and hold_n
                else (f'<small class="k">진행 중 없음</small>' if key in tab_idx else ""))
        sub = f'{E(main)}' + (f' · 기대 {num(e[1])}' if with_expect and e[1] is not None else "")
        name_cell = (f'<b id="perf-{key.replace(" ", "-")}">{E(label)}</b> {badge}<small class="k">{sub}</small>'
                     + (f'<small class="k">{extra(g["수익률(%)"])}</small>' if n else "")
                     + (f'<small class="k">그 밖: {" · ".join(others)}</small>' if others else "") + link)
        small = n < 30
        val = (f'<span class="{"thin" if small else ""}">{num(a)}</span><small class="k">승률 {f"{w:.0f}%" if w is not None else "–"} · {n}건</small>'
               + (f'<small class="k">표본 부족 {n}/30</small>' if small else "")) if n else '<span class="empty">–</span><small class="k">끝난 매매 0건</small>'
        rows.append(("muted" if n == 0 and not hold_n else "", [name_cell, val]))
    return wide(["매매법", "평균"], rows, right=(1,))


HOLD_TABS = [("저가매수", "저가매수", "엔벨로프 아래로 빠지면 3번 나눠 사고, 20일선 회복에 팔아요. 1차 신호(종가가 20일선보다 10% 아래)가 나면 칸이 채워져요."),
             ("스윙 A", "스윙 A", "급락 눌림 신호가 난 다음 날 시가에 사서 5일 보유, 손절 -10%. 신호가 드물어 비어 있는 날이 많아요."),
             ("중기 스윙", "CAN SLIM", "실적 A등급 + 바닥 돌파 종목을 사서 -8% 손절, +20%에 절반. 코스피·코스닥이 20일선 위로 회복되면 신호가 나와요."),
             ("종가베팅", "종가베팅", "15:10 후보를 종가에 사서 다음 날 시가에 팔아요(하룻밤 보유). 시장이 20일선 위로 회복되면 다시 시작해요.")]


def hold_rows(g):
    rows = []
    for r in g.to_dict("records"):
        kind = r.get("구분") or ""
        kb = f'<span class="badge {"test" if kind == "모의" else "real"}">{E(kind)}</span>' if kind else ""
        todo = []
        if fnum(r.get("다음 매수가")):
            todo.append(f'추가 매수 ≤{fnum(r["다음 매수가"]):,.0f}')
        if r.get("매도 기준") and r.get("매도 기준") == r.get("매도 기준"):
            todo.append(f'매도 {E(r["매도 기준"])}')
        if fnum(r.get("손절가")):
            todo.append(f'손절 {fnum(r["손절가"]):,.0f}')
        elif r.get("손절 메모") and r.get("손절 메모") == r.get("손절 메모"):
            todo.append(f'<small>손절 {E(r["손절 메모"]).replace("2차 매수 뒤부터 ", "2차 뒤 ")}</small>')
        days_ = f'{int(fnum(r.get("보유일")))}일째' if fnum(r.get("보유일")) else ""
        rows.append([f'<b>{E(r["종목"])}</b> {kb}<small class="k">{E(r["상태"])} · {days_}</small>',
                     num(r.get("수익률(%)")) + f'<small class="k">{fnum(r.get("현재가")) or 0:,.0f} / 평단 {fnum(r.get("평단")) or 0:,.0f}</small>',
                     "<br>".join(todo)])
    return rows


def holdings(h):
    """매매법마다 한 장씩, 탭을 누르거나 옆으로 밀어서 넘겨 봄"""
    base = h["매매법"].astype(str).str.split("(").str[0] if len(h) else pd.Series(dtype=str)
    tabs, panes = [], []
    for i, (key, label, note) in enumerate(HOLD_TABS):
        g = h[base == key] if len(h) else h
        n, w, a = stat(g["수익률(%)"]) if len(g) else (0, None, None)
        tabs.append(f'<a href="#hp-{i}" data-i="{i}" class="{"on" if i == 0 else ""}">{label} <b>{len(g)}</b></a>')
        st = STATUS.get(key, "")
        badge = f'<span class="badge {"test" if st.startswith("테스트") else "ok"}">{E(st.split(" (")[0].split(" ·")[0])}</span>' if st else ""
        head = (f'<p class="kpi"><b>{label}</b> {badge} <small>{STAGE[key]}</small> · {len(g)}종목' + (f' · 평가 평균 {num(a)}' if len(g) else "")
                + f' <a class="go" href="#perf-{key.replace(" ", "-")}">성적 보기 ›</a></p>')
        body = wide(["종목", "평가 수익률", "다음 할 일"], hold_rows(g), right=(1,)) if len(g) else '<p class="empty">지금 들고 있는 종목 없음</p>'
        panes.append(f'<section class="pane" id="hp-{i}">{head}{body}<p class="sub">{E(note)}</p></section>')
    n, w, a = stat(h["수익률(%)"]) if len(h) else (0, None, None)
    top = f'<p class="kpi">전체 {len(h)}종목 · 평가 평균 {num(a)} <small>(아직 팔지 않은 손익, 최근 종가 기준)</small></p>'
    js = """<script>{const c=document.querySelector('.panes'),t=[...document.querySelectorAll('.htabs a')];
if(c&&t.length){c.addEventListener('scroll',()=>{const i=Math.round(c.scrollLeft/c.clientWidth);t.forEach((a,j)=>a.classList.toggle('on',j===i))},{passive:true});
t.forEach(a=>a.addEventListener('click',e=>{e.preventDefault();c.scrollTo({left:c.clientWidth*(+a.dataset.i),behavior:'smooth'})}))}}</script>"""
    return (top + f'<nav class="htabs">{"".join(tabs)}</nav><div class="panes">{"".join(panes)}</div>'
            '<p class="sub">탭을 누르거나 표를 옆으로 밀면 다른 매매법으로 넘어가요.</p>' + js)


def real_block():
    pos = read(os.path.join(REC, "real", "positions.csv"))
    trd = read(os.path.join(REC, "real", "trades.csv"))
    if not len(pos) and not len(trd):
        return '<p class="empty">실제 계좌 기록 없음</p>', None
    try:
        import market_data as md
        L = md.all_stocks(); price = dict(zip(L.code, L.price))
    except Exception:
        price = {}
    rows, rets = [], []
    for r in pos.itertuples():
        c = price.get(r.코드); avg = fnum(r.평단)
        ret = (c / avg - 1) * 100 if c and avg else None
        if ret is not None:
            rets.append(ret)
        rows.append([f'<b>{E(r.종목)}</b> <span class="badge real">실제</span><small class="k">{E(r.계좌)} · {E(fmt_d(str(r.시작일), False))}부터 기록</small>',
                     num(ret) + f'<small class="k">{(c or 0):,.0f} / 평단 {(avg or 0):,.0f}</small>', E(r.계획 if isinstance(r.계획, str) else "")])
    html_ = wide(["종목", "평가 수익률", "계획"], rows, right=(1,)) if rows else ""
    if len(trd):
        tr = [[f'<b>{E(r.종목)}</b><small class="k">{E(r.계좌)} · {E(r.구분)} 매도 · {E(fmt_d(str(r.날짜), False))}</small>', num(r._8),
               f'{fnum(r.평단) or 0:,.0f} → {fnum(r.매도가) or 0:,.0f}'] for r in trd.itertuples()]
        html_ += "<h3>판 기록</h3>" + wide(["종목", "수익률", "평단 → 매도가"], tr, right=(1,))
    html_ += ('<p class="sub">키움은 평일 16:13 노트북이 잔고를 읽어 자동으로 맞춰요. 미래에셋 등은 봇에게 '
              '"실제 종목 평단 계좌", "실제매도 종목 매도가", "실제일부매도 종목 매도가", "실제계획 종목 내용"으로 알려 주세요. 수량·금액은 저장하지 않아요.</p>')
    avg_ret = sum(rets) / len(rets) if rets else None
    return html_, (len(pos), avg_ret)


def leaders_table(lead, d, mk):
    x = lead[lead.date == d] if len(lead) else lead
    if not len(x):
        return '<p class="empty">대장주 기록 없음</p>'
    rows = []
    for r in x.itertuples():
        th = theme_of(r, mk)
        rows.append([f'<span class="bar" style="--c:{color(th)}"></span><b>{E(r.name)}</b><small class="k">{chip(th)}</small>', num(r.ret, 1),
                     num(getattr(r, "next_close", None), 1), num(getattr(r, "next_open", None), 1), f"{fnum(r.value):,.0f}억", E(r.reason)])
    return wide(["종목", "그날", "다음날 종가", "다음날 시가", "거래대금", "오른 이유 후보"], rows, right=(1, 2, 3, 4))


def m15_table(fm, ds):
    x = fm[fm.date.isin(ds)] if len(fm) else fm
    if not len(x):
        return '<p class="empty">신호 없음</p>'
    n, w, a = stat(x.ret)
    rows = [[f'<b>{E(r.name)}</b><small class="k">{fmt_d(r.date, False)} {int(r.t_in) // 100:02d}:{int(r.t_in) % 100:02d}→{int(r.t_out) // 100:02d}:{int(r.t_out) % 100:02d}</small>',
             num(r.ret), E(r.why), f"{r.buy:,.0f}", f"{r.sell:,.0f}"] for r in x.itertuples()]
    return (f'<p class="kpi">{n}건 · 승률 {w:.0f}% · 평균 {num(a)} <small>1건 100만원, 비용 0.35% 뺌 · 1년 검증 기대 -0.41%</small></p>'
            + wide(["종목", "수익률", "매도 이유", "매수가", "매도가"], rows, right=(1, 3, 4)))


def vi_table(vi, ds):
    x = vi[vi.date.isin(ds)] if len(vi) else vi
    if not len(x):
        return '<p class="empty">VI 복기 기록 없음</p>'
    rows = []
    for r in x.to_dict("records"):
        rows.append(("muted" if r["구분"] != "정식" else "", [f'<b>{E(r["종목명"])}</b><small class="k">{fmt_d(r["date"], False)} {E(str(r["VI시각"])[:5])} · {E(r["구분"])}</small>',
                                                          num(r.get("수익률(%)")), E(r["결과"]), num(r.get("VI후최고(%)"), 1), num(r.get("VI후최저(%)"), 1), num(r.get("종가(%)"), 1)]))
    o = x[x["구분"] == "정식"]
    n, w, a = stat(o["수익률(%)"]) if len(o) else (0, None, None)
    head = f'<p class="kpi">정식 시간 {len(o)}건 중 매매 {n}건' + (f" · 승률 {w:.0f}% · 평균 {num(a)}" if n else "") + ' <small>흐린 줄은 시간 밖(참고)</small></p>'
    return head + wide(["종목", "수익률", "결과", "VI 뒤 최고", "VI 뒤 최저", "종가"], rows, right=(1, 3, 4, 5))


def msg_html(m):
    body = m["text"] if m.get("html") else E(m["text"])
    body = body.replace("\n<pre>", "<pre>").replace("</pre>\n", "</pre>").replace("\n\n", "\n")
    tag = '<span class="src vi">노트북 VI봇</span>' if m["src"] == "VI" else ""
    return f'<article class="msg"><time>{E(m["t"])}</time><div class="bubble">{tag}{body}</div></article>'


def trades_wide(t):
    if not len(t):
        return '<p class="empty">끝난 매매 없음</p>'
    t = t.assign(_s=t.매매법.map(lambda s: STAGE_ORDER.index(STAGE.get(s, "중기 스윙")))).sort_values(["_s", "매매법"])
    rows = [[f'<b>{E(r["종목"])}</b><small class="k">{E(SHOW_NAME.get(r["매매법"], r["매매법"]))} · {E(r["구분"])}</small>', num(r["수익률(%)"]),
             E(r["산 날"]), E(r["판 날"]), E(r["메모"])] for r in t.to_dict("records")]
    return wide(["종목", "수익률", "산 날", "판 날", "메모"], rows, right=(1,))


# ---------- 그래프 (SVG) ----------
CURVE_KEEP = [("VI 단타", "자동 복기(정식 시간)"), (M15, "모의"), ("종가베팅", "모의(알려준 후보)"), ("종가베팅", "실제"),
              ("저가매수", "내 5칸"), ("스윙 A", "모의"), ("중기 스윙", "모의"), ("중기 스윙", "실제")]
LINE_COLORS = ["#5b6ee1", "#e8a317", "#e3120b", "#c4161c", "#3c8d5a", "#16a085", "#8e44ad", "#6c3483"]


def curve_svg(t):
    """매매법별 누적 수익률 (같은 금액 넣었다고 가정, 판 날 순서로 더함)"""
    if not len(t):
        return '<p class="empty">아직 끝난 매매가 없어요.</p>'
    series, few = [], []
    for i, (s_, k) in enumerate(CURVE_KEEP):
        g = t[(t.매매법 == s_) & (t.구분 == k)].copy()
        if len(g) < 5:
            if len(g):
                few.append(f"{SHOW_NAME.get(s_, s_)}·{k} {len(g)}건")
            continue
        g = g.sort_values("판 날")
        g["cum"] = pd.to_numeric(g["수익률(%)"], errors="coerce").fillna(0).cumsum()
        series.append((f"{SHOW_NAME.get(s_, s_)} · {k}", LINE_COLORS[i % len(LINE_COLORS)], list(zip(g["판 날"].astype(str), g.cum, g["종목"])),
                       STATUS.get(s_, "").startswith("테스트")))
    note = f'<p class="sub">5건이 안 돼서 아직 선을 그리지 않은 것: {E(", ".join(few))}</p>' if few else ""
    if not series:
        return '<p class="empty">5건 넘게 쌓인 매매법이 아직 없어요.</p>' + note
    dates = sorted({d for _, _, pts, _ in series for d, _, _ in pts})
    if len(dates) == 1:
        dates = [dates[0], dates[0]]
    vals = [v for _, _, pts, _ in series for _, v, _ in pts] + [0]
    lo, hi = min(vals), max(vals)
    pad = (hi - lo) * 0.1 or 1
    lo, hi = lo - pad, hi + pad
    W, H, L, R, T, B = 640, 260, 46, 12, 10, 26
    xi = {d: i for i, d in enumerate(dates)}
    X = lambda d: L + (W - L - R) * (xi[d] / max(1, len(dates) - 1))
    Y = lambda v: T + (H - T - B) * (hi - v) / (hi - lo)
    g = [f'<line x1="{L}" x2="{W - R}" y1="{Y(0):.1f}" y2="{Y(0):.1f}" class="zero"/>']
    for k in range(5):
        v = lo + (hi - lo) * k / 4
        g.append(f'<text x="{L - 6}" y="{Y(v) + 4:.1f}" text-anchor="end">{v:+.0f}%</text>')
    step = max(1, len(dates) // 6)
    for d in dates[::step]:
        g.append(f'<text x="{X(d):.1f}" y="{H - 6}" text-anchor="middle">{int(d[5:7])}/{int(d[8:10])}</text>')
    legend = []
    for name, c, pts, test in series:
        path = " ".join(f"{'M' if j == 0 else 'L'}{X(d):.1f},{Y(v):.1f}" for j, (d, v, _) in enumerate(pts))
        dash_ = ' stroke-dasharray="5 4"' if test else ""
        g.append(f'<path d="{path}" fill="none" stroke="{c}" stroke-width="2.2"{dash_}/>')
        for d, v, nm in pts:
            g.append(f'<circle cx="{X(d):.1f}" cy="{Y(v):.1f}" r="3.5" fill="{c}"><title>{E(name)} · {d} {E(nm)} · 누적 {v:+.2f}%</title></circle>')
        legend.append(f'<span><i style="background:{c}"></i>{E(name)}{" (테스트 중, 점선)" if test else ""}</span>')
    return (f'<div class="legend">{"".join(legend)}</div><div class="chart"><svg viewBox="0 0 {W} {H}" role="img" aria-label="매매법별 누적 수익률">{"".join(g)}</svg></div>'
            '<p class="sub">끝난 매매의 수익률을 판 날 순서로 더한 값(매매마다 같은 금액 가정). 점을 누르면 종목과 누적값이 나와요.</p>' + note)


def index_svg(code, label, n=40):
    """지수 선 + 20일선(점선) + 거래량 막대. 지수가 20일선 아래인 구간은 바탕을 옅게 칠함"""
    try:
        import market_data as md
        x = md.daily(code, n + 25).reset_index(drop=True)
    except Exception:
        return ""
    x["ma20"] = x.c.rolling(20).mean()
    x = x.tail(n).reset_index(drop=True)
    if len(x) < 5:
        return ""
    W, H, L, R, T = 640, 250, 52, 10, 10
    PH, VH, GAP, B = 150, 50, 10, 22          # 지수 칸, 거래량 칸, 사이, 아래 글씨
    lo, hi = min(x.l.min(), x.ma20.min()), max(x.h.max(), x.ma20.max())
    pad = (hi - lo) * 0.06
    lo, hi = lo - pad, hi + pad
    m = len(x); bw = (W - L - R) / m
    X = lambda i: L + bw * (i + 0.5)
    Y = lambda v: T + PH * (hi - v) / (hi - lo)
    vmax = x.v.max() or 1
    VY0 = T + PH + GAP + VH
    g = []
    for i, r in x.iterrows():          # 20일선 아래인 날은 바탕을 옅게
        if r.ma20 == r.ma20 and r.c < r.ma20:
            g.append(f'<rect x="{L + bw * i:.1f}" y="{T}" width="{bw:.1f}" height="{PH}" class="below"/>')
    for k in range(4):
        v = lo + (hi - lo) * k / 3
        g.append(f'<line x1="{L}" x2="{W - R}" y1="{Y(v):.1f}" y2="{Y(v):.1f}" class="grid"/><text x="{L - 6}" y="{Y(v) + 4:.1f}" text-anchor="end">{v:,.0f}</text>')
    ma = " ".join(f"{'M' if j == 0 else 'L'}{X(i):.1f},{Y(v):.1f}" for j, (i, v) in enumerate((i, v) for i, v in x.ma20.items() if v == v))
    g.append(f'<path d="{ma}" fill="none" stroke="var(--mute)" stroke-width="1.6" stroke-dasharray="5 4"/>')
    cl = " ".join(f"{'M' if i == 0 else 'L'}{X(i):.1f},{Y(v):.1f}" for i, v in x.c.items())
    g.append(f'<path d="{cl}" fill="none" stroke="var(--ink)" stroke-width="2.2"/>')
    for i, r in x.iterrows():
        up = i == 0 or r.c >= x.c[i - 1]
        h_ = VH * r.v / vmax
        chg = (r.c / x.c[i - 1] - 1) * 100 if i else 0
        d = r.date
        g.append(f'<a href="{"m/" + d + ".html" if market(d) else "#"}"><rect x="{L + bw * i + bw * 0.15:.1f}" y="{VY0 - h_:.1f}" width="{bw * 0.7:.1f}" height="{max(1, h_):.1f}" '
                 f'fill="var({"--up" if up else "--dn"})" opacity=".55"><title>{int(d[4:6])}/{int(d[6:])} {label} {r.c:,.2f} ({chg:+.2f}%) · 20일선 {r.ma20:,.0f} · 거래량 {r.v:,.0f}천주</title></rect></a>')
        g.append(f'<circle cx="{X(i):.1f}" cy="{Y(r.c):.1f}" r="7" fill="transparent"><title>{int(d[4:6])}/{int(d[6:])} {label} {r.c:,.2f} ({chg:+.2f}%) · 20일선 {r.ma20:,.0f}</title></circle>')
    g.append(f'<text x="{L - 6}" y="{VY0 - VH + 10}" text-anchor="end">거래량</text>')
    step = max(1, m // 6)
    for i in range(0, m, step):
        d = x.date[i]
        g.append(f'<text x="{X(i):.1f}" y="{H - 4}" text-anchor="middle">{int(d[4:6])}/{int(d[6:])}</text>')
    last = x.iloc[-1]
    gap = (last.c / last.ma20 - 1) * 100
    head = (f'<h3>{label} <b>{last.c:,.2f}</b> {num((last.c / x.c.iloc[-2] - 1) * 100)} '
            f'<small>· 20일선 {last.ma20:,.0f} ({num(gap, 1)} {"위" if gap > 0 else "아래"})</small></h3>')
    return head + f'<div class="chart"><svg viewBox="0 0 {W} {H}" role="img" aria-label="{label} 지수와 20일선, 거래량">{"".join(g)}</svg></div>'


def market_bars_svg(days, n=40):
    a, b = index_svg("KOSPI", "코스피", n), index_svg("KOSDAQ", "코스닥", n)
    if not (a or b):
        return '<p class="empty">지수 데이터를 받지 못했어요.</p>'
    return ('<div class="legend"><span><i style="background:var(--ink)"></i>지수</span><span><i style="background:var(--mute)"></i>20일선(점선)</span>'
            '<span><i style="background:color-mix(in srgb,var(--dn) 25%,transparent)"></i>20일선 아래 구간</span><span><i style="background:var(--up)"></i>거래량(오른 날 빨강, 내린 날 파랑)</span></div>'
            + a + b + '<p class="sub">지수가 20일선(점선) 위로 올라가야 종가베팅·신규 매수를 다시 해요. 거래량 막대를 누르면 그날 시장 페이지가 열려요.</p>')


# ---------- 달력 ----------
def month_cal(ym, days_set, cell, href, week_link=True, tint=None):
    y, m = int(ym[:4]), int(ym[4:])
    head = ('<div class="cal-h">주</div>' if week_link else "") + "".join(f'<div class="cal-h">{w}</div>' for w in "월화수목금")
    body = ""
    for wk in calendar.Calendar(0).monthdatescalendar(y, m):
        mon = wk[0].strftime("%Y%m%d")
        if not any(x.month == m for x in wk[:5]):
            continue
        if week_link:
            has = any(x.strftime("%Y%m%d") in days_set for x in wk[:5])
            body += (f'<a class="cal-w" href="{href("w:" + mon)}">{wk[0].month}/{wk[0].day}<br>주간</a>' if has else '<div class="cal-w off"></div>')
        for x in wk[:5]:
            d = x.strftime("%Y%m%d")
            if x.month != m:
                body += '<div class="cal-d off"></div>'
            elif d in days_set:
                v = tint(d) if tint else None
                st = ""
                if v is not None:
                    pct = min(abs(v) / 4, 1) * 30 + 6       # 많이 움직일수록 진하게 (4% 이상이면 가장 진함)
                    st = f' style="background:color-mix(in srgb,var({"--up" if v > 0 else "--dn"}) {pct:.0f}%,var(--bg))"'
                body += f'<a class="cal-d" href="{href(d)}"{st}><b>{x.day}</b>{cell(d)}</a>'
            else:
                body += f'<div class="cal-d none"><b>{x.day}</b></div>'
    return f'<section class="month"><h3>{y}년 {m}월</h3><div class="cal {"cal6" if week_link else "cal5"}">{head}{body}</div></section>'


def months(days):
    return sorted({d[:6] for d in days}, reverse=True)


def alert_cell(d, t):
    ms = messages(d)
    td = t[t["판 날"].astype(str).str.replace("-", "") == d] if len(t) else t
    s = f'<span class="dot">알림 {len(ms)}</span>' if ms else ""
    if len(td):
        real = td[td.구분 == "실제"]
        mock = td[(td.구분 != "실제") & ~td.구분.str.contains("참고")]
        if len(real):
            n, w, a = stat(real["수익률(%)"])
            s += f'<span class="dot">실제 {n}건 {num(a, 1)}</span>'
        if len(mock):
            s += f'<span class="dot">모의 {len(mock)}건</span>'
    return s


def mkt_tint(d):
    mk = market(d)
    if not mk:
        return None
    v = [x for x in (fnum(mk.get("kospi")), fnum(mk.get("kosdaq"))) if x is not None]
    return sum(v) / len(v) if v else None


ALIAS = {"태양광에너지": "태양광", "엔터테인먼트": "엔터", "지능형로봇/인공지능": "AI로봇", "코리아밸류업지수": "밸류업지수",
         "밸류업": "밸류업", "원자력발전": "원전", "카메라모듈/부품": "카메라모듈", "고체산화물연료전지": "SOFC", "우주항공산업": "우주항공",
         "반도체재료/부품": "반도체소재", "반도체기판": "반도체기판", "전후재건": "전후재건", "증강현실": "AR", "보안주": "보안주",
         "코로나19": "코로나", "양자암호/양자컴퓨팅": "양자", "로봇": "로봇", "전력저장장치": "ESS", "모바일게임": "모바일게임",
         "제약업체": "제약", "음원/음반": "음원", "PCB": "PCB", "남북경협": "남북경협", "소매유통": "유통", "지주사": "지주사", "통신장비": "통신장비"}


def short_theme(th):
    t = th.split("(")[0].replace(" ", "")
    if t in ALIAS:
        return ALIAS[t]
    return t.split("/")[0][:6]


def market_cell(d, lead):
    mk = market(d)
    s = ""
    if mk:
        s += f'<span>코 {num(mk.get("kospi"), 1)}</span><span>닥 {num(mk.get("kosdaq"), 1)}</span>'
        th = (mk.get("hot") or [{}])[0].get("name") or (mk.get("themes") or [{}])[0].get("name")
        if th:
            s += f'<span class="chip" style="--c:{color(th)}">{E(short_theme(th))}</span>'
    elif len(lead) and (lead.date == d).any():
        s += f'<span class="dot">{E(lead[lead.date == d].name.iloc[0])}</span>'
    return s


# ---------- 페이지 ----------
CSS = """
#acct .kpis{grid-template-columns:repeat(2,1fr)}
.syncrow{display:flex;flex-wrap:wrap;align-items:center;gap:8px 12px;margin:10px 0}
.syncbtn{display:inline-flex;align-items:center;min-height:44px;padding:8px 18px;border-radius:999px;background:var(--red);color:#fff;font-weight:700;text-decoration:none}
table.rank td.rk1{background:color-mix(in srgb,var(--red) 22%,transparent);font-weight:700}table.rank td.rk2{background:color-mix(in srgb,var(--red) 12%,transparent)}
table.rank td.rk0{color:var(--line)}
ul.tl{list-style:none;padding:0;margin:0}ul.tl li{padding:5px 0;border-bottom:1px solid var(--line)}ul.tl time,.fold summary time,.kpi time{font-weight:700;color:var(--slate);margin-right:6px}
.new{font-size:11.5px;font-weight:700;color:#fff;background:var(--slate);padding:0 5px;border-radius:3px}.nowrap{white-space:nowrap}

/* VOICE 신문 경제면처럼 차분하게 / IDEA 매일 넘겨 보는 투자 알림장 / PICTURE 달력과 말풍선
   COLOUR 흰 바탕·먹색·빨간 탭·슬레이트, 테마 12색 / TYPE Noto Serif KR 제목 + Noto Sans KR 본문 / LAYOUT 한 단, 휴대폰 우선, 표는 옆으로 밀기 */
:root{color-scheme:light dark;--bg:light-dark(#fff,#10191e);--ink:light-dark(#121212,#e9eef0);--mute:light-dark(#5b6670,#9aa8b1);
--red:#e3120b;--slate:light-dark(#2e6f8e,#7fb6cf);--panel:light-dark(#eef3f5,#18252c);--line:light-dark(#d5dde2,#2a3a43);
--up:light-dark(#c4161c,#ff6b66);--dn:light-dark(#1f5fbf,#6aa4ff)}
:root[data-theme=light]{color-scheme:light}:root[data-theme=dark]{color-scheme:dark}
*{box-sizing:border-box;min-width:0}
body{margin:0;background:var(--bg);color:var(--ink);font:16px/1.6 "Noto Sans KR",system-ui,sans-serif;overflow-x:clip}
a{color:var(--slate)}
header{border-top:6px solid var(--red);padding:18px max(4vw,14px) 4px;max-width:1080px;margin:auto}
header .tab{display:inline-block;background:var(--red);color:#fff;font-weight:700;font-size:13px;padding:2px 10px;margin-bottom:8px}
h1{font:700 clamp(28px,5vw,42px)/1.15 "Noto Serif KR",serif;margin:0 0 4px;text-wrap:balance}
h2{font:700 21px/1.3 "Noto Serif KR",serif;margin:34px 0 10px;padding-top:10px;border-top:1px solid var(--line)}
h3{font:700 16px/1.3 "Noto Sans KR",sans-serif;margin:16px 0 8px}
main{max-width:1080px;margin:auto;padding:0 max(4vw,14px) 60px}
.sub{color:var(--mute);margin:0 0 8px}
nav.tabs{display:flex;gap:8px;overflow-x:auto;padding:12px 0 2px}
nav.tabs a{flex:none;display:flex;align-items:center;padding:6px 14px;border:1px solid var(--line);border-radius:999px;text-decoration:none;color:var(--ink);font-size:14px;min-height:40px}
nav.tabs a.on{background:var(--ink);color:var(--bg);border-color:var(--ink)}
.kpis{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:1px;background:var(--line);border:1px solid var(--line);margin:14px 0}
.kpis div{background:var(--bg);padding:12px 14px}.kpis b{display:block;font:700 24px/1.25 "Noto Serif KR",serif}.kpis div>span{color:var(--mute);font-size:13px}
.kpi{margin:4px 0 10px}
.scroll{overflow-x:auto;-webkit-overflow-scrolling:touch;border:1px solid var(--line);border-radius:6px}
table.wide{border-collapse:collapse;min-width:100%;font-size:14.5px}
.wide th,.wide td{padding:8px 12px;border-bottom:1px solid var(--line);text-align:left;white-space:nowrap;vertical-align:middle}
.wide tr:last-child td{border-bottom:0}
.wide th{font-size:12.5px;color:var(--mute);font-weight:500;background:var(--panel)}
.wide td:first-child,.wide th:first-child{position:sticky;left:0;z-index:1;background:var(--bg);box-shadow:1px 0 0 var(--line)}.wide th:first-child{background:var(--panel)}
.wide tr.group td{background:var(--panel);font-size:13.5px;padding:6px 12px;border-top:2px solid var(--ink);position:static;box-shadow:none}.wide tr.muted td{color:var(--mute)}
.wide td small{color:var(--mute);font-size:12px}
.r{text-align:right!important}
.up{color:var(--up);font-weight:600}.dn{color:var(--dn);font-weight:600}
.empty{color:var(--mute)}small{color:var(--mute)}
.chip{display:inline-block;padding:1px 8px;border-radius:4px;font-size:12.5px;font-weight:600;color:var(--c);background:color-mix(in srgb,var(--c) 14%,transparent);border-left:3px solid var(--c);white-space:nowrap}
.bar{display:inline-block;width:4px;height:16px;background:var(--c);margin-right:7px;vertical-align:-3px;border-radius:2px}
.msg{display:grid;grid-template-columns:48px 1fr;gap:8px;margin:12px 0}
.msg time{font-weight:700;color:var(--slate);padding-top:10px;font-size:14px}
.bubble{background:var(--panel);border-radius:4px 14px 14px 14px;padding:11px 14px;white-space:pre-wrap;overflow-wrap:anywhere;font-size:15px}
.bubble pre{margin:4px 0 8px;white-space:pre;overflow-x:auto;font:13.5px/1.55 ui-monospace,"D2Coding",monospace;background:var(--bg);padding:8px 10px;border-radius:6px}
.src{display:inline-block;font-size:12px;font-weight:700;padding:0 6px;border-radius:4px;margin-right:6px}.src.vi{background:#5b6ee1;color:#fff}
.cal{display:grid;gap:4px}.cal6{grid-template-columns:48px repeat(5,minmax(0,1fr))}.cal5{grid-template-columns:repeat(5,minmax(0,1fr))}
.cal-h{font-size:12px;color:var(--mute);text-align:center}
.cal-d,.cal-w{min-height:84px;border:1px solid var(--line);border-radius:6px;padding:5px 6px;text-decoration:none;color:var(--ink);font-size:12px;line-height:1.4;display:flex;flex-direction:column;gap:2px;overflow:hidden}
.cal-d b{font-size:14px}.cal-d.none{color:var(--mute);opacity:.5}.cal-d.off,.cal-w.off{border:0}
a.cal-d{background:var(--panel)}a.cal-d:hover,a.cal-w:hover,a.cal-d:focus-visible{outline:2px solid var(--slate)}
.cal-w{align-items:center;justify-content:center;text-align:center;font-weight:700;color:var(--slate);font-size:12px}
.cal-d .chip{font-size:11px;padding:0 3px;overflow:hidden;white-space:nowrap;max-width:100%}
.dot{font-size:11.5px;color:var(--mute)}
.wide td small.k{display:block;font-size:12px;color:var(--mute);font-weight:400;margin-top:1px}
.wide td:first-child{white-space:normal;min-width:130px;max-width:190px}
.today{margin:14px 0 0;padding:12px 14px;border-left:4px solid var(--red);background:var(--panel);font-size:15px;line-height:1.7}
.today a{color:var(--ink);text-decoration:none;display:block}
.kpis{grid-template-columns:repeat(2,minmax(0,1fr))}@media(min-width:760px){.kpis{grid-template-columns:repeat(4,minmax(0,1fr))}}
.kpis div>span{display:block;line-height:1.45}
details.fold{border-bottom:1px solid var(--line)}details.fold summary{padding:10px 0;display:flex;gap:10px;align-items:center;list-style:none}
details.fold summary::before{content:"▸";color:var(--slate)}details.fold[open] summary::before{content:"▾"}
details.fold summary time{font-weight:700;color:var(--slate)}details.fold .msg{margin-top:0}
.badge{display:inline-block;font-size:11px;font-weight:700;padding:0 6px;border-radius:4px;vertical-align:1px;white-space:nowrap}
.badge.real{background:var(--ink);color:var(--bg)}.badge.test{background:#f3c64a;color:#3a2a00}.badge.ok{background:color-mix(in srgb,#3c8d5a 18%,transparent);color:#2f7a4a}
.chart svg{width:100%;height:auto;display:block}.chart .grid{stroke:var(--line);stroke-width:.6}.chart .below{fill:color-mix(in srgb,var(--dn) 9%,transparent)}.chart text{font-size:12px;fill:var(--mute)}.chart .zero{stroke:var(--line);stroke-width:1.5}
.legend{display:flex;flex-wrap:wrap;gap:4px 14px;font-size:13px;color:var(--mute);margin:4px 0 6px}.legend i{display:inline-block;width:10px;height:10px;border-radius:50%;margin-right:5px;vertical-align:-1px}
.thin{opacity:.45}.kpis div:first-child{grid-column:1/-1}.cnt{display:inline-block;white-space:nowrap;margin:0 8px 6px 0}ul.plain{list-style:none;padding:0;margin:4px 0}ul.plain li{padding:6px 0;border-bottom:1px solid var(--line)}
.kpis{grid-template-columns:repeat(2,minmax(0,1fr))}@media(min-width:760px){.kpis{grid-template-columns:repeat(3,minmax(0,1fr))}}
.wide td:last-child{white-space:normal;min-width:110px;font-size:13.5px}
.kpis.links a{display:block;position:relative;background:var(--bg);padding:12px 26px 12px 14px;color:var(--ink);text-decoration:none}
.kpis.links a:nth-child(-n+2){grid-column:auto}.kpis.links a.wide{grid-column:1/-1}.kpis.links a:active,.kpis.links a:hover{background:var(--panel)}
.kpis.links em{position:absolute;right:10px;top:50%;transform:translateY(-50%);font-style:normal;font-size:22px;color:var(--mute)}
.kpis.links .kv{display:block;font:700 24px/1.25 "Noto Serif KR",serif}.kpis.links .kl{color:var(--mute);font-size:13px;display:block;line-height:1.5}
.flash{background:color-mix(in srgb,#f3c64a 45%,transparent);transition:background .4s}html{scroll-behavior:smooth;scroll-padding-top:16px}
.htabs{display:flex;gap:6px;overflow-x:auto;padding:4px 0 8px}.htabs a{flex:none;padding:6px 12px;border:1px solid var(--line);border-radius:999px;text-decoration:none;color:var(--ink);font-size:14px;min-height:38px;display:flex;align-items:center;gap:5px}
.htabs a.on{background:var(--ink);color:var(--bg);border-color:var(--ink)}.htabs a b{font-weight:700;opacity:.8}
.panes{display:flex;overflow-x:auto;scroll-snap-type:x mandatory;gap:16px;scrollbar-width:none;-webkit-overflow-scrolling:touch}.panes::-webkit-scrollbar{display:none}
.pane{flex:0 0 100%;scroll-snap-align:start;min-width:0}
a.go{display:inline-block;margin-top:4px;font-size:13px;font-weight:600;text-decoration:none;color:var(--slate)}
.pbar{position:sticky;top:0;z-index:5;background:var(--bg);padding:6px 0;border-bottom:1px solid var(--line)}
.pnavs{display:flex;gap:8px;margin-top:4px}.pnav{flex:1;min-height:40px;border:1px solid var(--line);border-radius:8px;background:var(--panel);color:var(--ink);font:600 15px "Noto Sans KR",sans-serif}
.pnav:disabled{opacity:.4}.custom[hidden]{display:none!important}.custom{display:flex;gap:10px;flex-wrap:wrap;margin-top:6px}.dsel{display:flex;gap:6px;align-items:center;flex-wrap:wrap}.dsel>span{min-width:2.4em;font-weight:600}.custom select{font-size:16px;min-height:40px;padding:4px 8px;border:1px solid var(--line);border-radius:6px;background:var(--bg);color:var(--ink)}
.plabel small{display:block;font-size:14px;font-weight:500;color:var(--mute);margin-top:2px}
h2.plabel{border-top:0;margin-top:16px}
.heat{overflow-x:auto}.hm,.hg{display:flex;gap:3px}.hm span{width:14px;flex:none;font-size:11px;color:var(--mute);white-space:nowrap}
.hc{display:flex;flex-direction:column;gap:3px}.hc a,.hc i{width:14px;height:14px;border-radius:3px;display:block;background:var(--panel)}.hc i{opacity:.35}.hc i.x{opacity:0}#mapp .kpis div:first-child{grid-column:auto}
.bars{display:grid;gap:6px}.bar-row{display:grid;grid-template-columns:110px 1fr 44px;gap:8px;align-items:center}.bt{height:12px;background:var(--panel);border-radius:6px;overflow:hidden}.bt i{display:block;height:100%;border-radius:6px}
.bar-row b{text-align:right;font-size:14px}table.flow td,table.flow th{padding:6px 8px}
footer{color:var(--mute);font-size:13px;margin-top:40px}
@media(max-width:600px){.cal-d,.cal-w{min-height:70px;padding:4px;font-size:11px}.cal-d b{font-size:13px}.cal6{grid-template-columns:34px repeat(5,minmax(0,1fr))}.cal-w{font-size:10.5px}.wide th,.wide td{padding:7px 9px;font-size:14px}}
"""


def page(title, sub, body, nav="", depth=0):
    p = "../" * depth
    links = [("index.html", "처음"), ("index.html#cal", "알림 달력"), ("market.html", "대장주 달력")]
    navs = "".join(f'<a class="{"on" if nav == n else ""}" href="{p}{h}">{n}</a>' for h, n in links)
    return f"""<!DOCTYPE html><html lang="ko"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{E(title)}</title><link rel="preconnect" href="https://fonts.googleapis.com"><link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Noto+Sans+KR:wght@400;500;700&family=Noto+Serif+KR:wght@700&display=swap" rel="stylesheet">
<style>{CSS}</style></head><body><header><span class="tab">투자 알림장</span><h1>{E(title)}</h1><p class="sub">{sub}</p>
<nav class="tabs">{navs}</nav></header><main>{body}
<script>{{const o=()=>{{const t=location.hash&&document.getElementById(decodeURIComponent(location.hash.slice(1)));if(!t)return;const d=t.closest("details");if(d)d.open=true;t.scrollIntoView({{block:"center"}});t.classList.add("flash");setTimeout(()=>t.classList.remove("flash"),1600)}};addEventListener("hashchange",o);o()}}</script>
<footer>평일 15:10·19:00 알림 뒤 자동으로 새로 만들어집니다. 수익률은 비용 0.35%를 뺀 값이고, 모의 기록은 실제 매매가 아닙니다.</footer></main></body></html>"""


def ma20_gap():
    """코스피·코스닥이 20일선에서 몇 % 떨어져 있는지 (종가베팅·신규 매수 기준)"""
    out = {}
    try:
        import market_data as md
        for k in ("KOSPI", "KOSDAQ"):
            x = md.daily(k, 30)
            out[k] = (x.c.iloc[-1] / x.c.tail(20).mean() - 1) * 100
    except Exception:
        pass
    return out


def index_page(days, t, h, fm, vi, expect):
    body = ""
    gap = ma20_gap()
    if days:
        d0 = days[0]; mk = market(d0) or {}
        hot = (mk.get("hot") or mk.get("themes") or [{}])[0]
        lead0 = (mk.get("leaders") or [{}])[0]
        ms = messages(d0)
        line = f'<b>{fmt_d(d0)}</b> 코스피 {num(mk.get("kospi"))} · 코스닥 {num(mk.get("kosdaq"))}'
        if mk:
            line += f' · 오른 종목 <span class="up">{mk.get("adv", 0):,}</span> / 내린 종목 <span class="dn">{mk.get("dec", 0):,}</span>'
        if hot.get("name"):
            line += f'<br>1등 테마 {chip(hot["name"])} (대장 {E(hot.get("lead", ""))})'
        if lead0.get("name"):
            line += f'<br>오늘 대장주 <b>{E(lead0["name"])}</b> {num(lead0.get("ret"), 1)}' + (f' {chip(lead0.get("theme"))}' if lead0.get("theme") else "")
        line += f' · 알림 {len(ms)}개'
        body += f'<div class="today"><a href="m/{d0}.html">{line}</a></div>'
    k = []
    real_html, real_sum = real_block()
    if real_sum:
        k.append((num(real_sum[1]), f'실제 계좌 <span class="badge real">실제</span> {real_sum[0]}종목<br>평가 평균 (미래에셋 포함)', "#real"))
    if gap:
        on = all(v > 0 for v in gap.values())
        k.append((f'<span class="{"up" if on else "dn"}">{"매매 가능" if on else "매매 쉼"}</span>',
                  "종가베팅 · 신규 매수<br>코스피 20일선 " + f'{num(gap.get("KOSPI"), 1)}' + " · 코스닥 " + f'{num(gap.get("KOSDAQ"), 1)}', "#mkt"))
    if len(h):
        n, w, a = stat(h["수익률(%)"])
        k.append((num(a), f"모의 진행 중 {len(h)}종목<br>평가 평균 (아직 안 판 손익)", "#hold"))
    for s_, kinds, label in (("종가베팅", ("실제", "모의(알려준 후보)"), "종가베팅"), ("저가매수", ("내 5칸",), "저가매수 5칸"), ("중기 스윙", ("실제", "모의"), "CAN SLIM")):
        g = t[(t.매매법 == s_) & t.구분.isin(kinds)] if len(t) else t
        n, w, a = stat(g["수익률(%)"] if len(g) else [])
        k.append((f'<span class="{"thin" if n < 30 else ""}">{num(a)}</span>' if n else "–",
                  f'{label} <span class="badge ok">검증 통과</span><br>' + (f"끝난 {n}건" + (" · 표본 부족" if n < 30 else "") if n else "아직 끝난 매매 없음"),
                  f"#perf-{s_.replace(' ', '-')}"))
    body += '<div class="kpis links">' + "".join(f'<a href="{h_}"><b class="kv">{a}</b><span class="kl">{b}</span><em>›</em></a>' for a, b, h_ in k) + "</div>"
    body += '<p class="sub">테스트 중인 매매법(VI 단타, 15분봉 단타)은 <a href="#perf">아래 성적 표</a>와 그래프에서만 보여요.</p>'
    body += ('<h2 id="mock">모의 계좌 <small>키움 주문봇</small></h2><div id="acct"><p class="empty">불러오는 중…</p></div>'
             '<p><a href="flow.html">오늘 장중 흐름 (30분마다) →</a></p><script src="live.js" defer></script>')
    body += '<h2 id="real">실제 계좌</h2>' + real_html
    body += ('<h2 id="perf">매매법별 누적 성적</h2><p class="sub">보유 기간으로 4단계로 나눴어요. 30건이 안 된 숫자는 흐리게 보여요. '
             '"진행 중 n종목 ›"을 누르면 아래 진행 중 칸의 같은 매매법 장으로 넘어가요.</p>' + strat_rows(t, expect, h=h))
    body += '<h2 id="curve">누적 수익 흐름</h2>' + curve_svg(t)
    body += '<h2 id="hold">지금 진행 중 (모의)</h2>' + holdings(h)
    body += '<h2 id="mkt">시장 흐름</h2>' + market_bars_svg(days)
    ds = set(days)
    body += '<h2 id="cal">알림 달력</h2><p class="sub">날짜를 누르면 그날 알림이, 왼쪽 "주간"을 누르면 그 주 복기가 열려요.</p>'
    body += "".join(month_cal(ym, ds, lambda d: alert_cell(d, t), lambda d: f"w/{d[2:]}.html" if d.startswith("w:") else f"d/{d}.html", tint=mkt_tint) for ym in months(days)[:2])
    if days:
        ms = messages(days[0])
        body += f'<h2>최근 알림 · {fmt_d(days[0])}</h2>'
        import re as _re
        for m in ms[-6:]:
            first = _re.sub(r"<[^>]+>", "", m["text"].split("\n")[0])[:40]
            body += f'<details class="fold"><summary><time>{E(m["t"])}</time> {E(first)}</summary>{msg_html(m)}</details>'
        if not ms:
            body += '<p class="empty">저장된 알림 원문 없음</p>'
        body += f'<p><a href="d/{days[0]}.html">이날 전체 보기 →</a></p>'
    if len(t):
        body += f'<h2>최근 끝난 매매</h2><details class="fold"><summary>최근 30건 펼치기 (전체 {len(t)}건)</summary>' + trades_wide(t.head(30)) + "</details>"
    now = dt.datetime.now(dt.timezone(dt.timedelta(hours=9))).strftime("%m/%d %H:%M")
    return page("오늘의 알림장", f"마지막 갱신 {now}", body, "처음")


def day_page(d, t, fm, lead, vi):
    ms = messages(d)
    td = t[t["판 날"].astype(str).str.replace("-", "") == d] if len(t) else t
    body = f'<nav class="tabs"><a href="../m/{d}.html">이날 시장·대장주</a><a href="../w/{monday(d)}.html">이번 주 복기</a></nav>'
    body += (f'<h2>장중 흐름 <small>30분마다 · 데스크톱 봇</small></h2><div class="flow" data-d="{d}"><p class="empty">불러오는 중…</p></div>'
             '<script src="../live.js" defer></script>')
    body += "<h2>보낸 알림</h2>" + ("".join(msg_html(m) for m in ms) if ms else '<p class="empty">이날 저장된 알림 원문 없음 (봇은 11/20부터, 노트북 VI봇은 다시 켠 뒤부터 저장)</p>')
    body += "<h2>대장주</h2>" + leaders_table(lead, d, market(d))
    body += '<h2>초단타 · VI 단타 자동 복기 <span class="badge test">테스트 중</span></h2>' + vi_table(vi, [d])
    body += f'<h2>초단타 · {M15} 모의 <span class="badge test">테스트 중</span></h2>' + m15_table(fm, [d])
    body += "<h2>이날 끝난 매매 (전체)</h2>" + trades_wide(td)
    return page(fmt_d(d) + " 알림", f"알림 {len(ms)}개", body, depth=1)


HAS_D = set()


def market_page_day(d, lead):
    mk = market(d) or {}
    body = '<nav class="tabs">' + (f'<a href="../d/{d}.html">이날 알림</a>' if d in HAS_D or d >= "20261102" else "") + f'<a href="../w/{monday(d)}.html">그 주 복기</a><a href="../market.html">대장주 달력</a></nav>'
    if mk:
        k = [(num(mk.get("kospi")), "코스피"), (num(mk.get("kosdaq")), "코스닥"),
             (f'<span class="up">{mk.get("adv", 0):,}</span> <small>/</small> <span class="dn">{mk.get("dec", 0):,}</span>', "오른 종목 / 내린 종목"),
             (f'{mk.get("limit_up", 0)} <small>/</small> {mk.get("limit_down", 0)}', "상한가 / 하한가")]
        body += '<div class="kpis">' + "".join(f"<div><b>{a}</b><span>{b}</span></div>" for a, b in k) + "</div>"
        if mk.get("hot"):
            rows = [[chip(x["name"], False), str(x["n"]), f'<b>{E(x["lead"])}</b>', num(x["lead_ret"], 1), E(x.get("second", "")), num(x.get("second_ret"), 1)] for x in mk["hot"]]
            body += '<h2>돈이 몰린 테마</h2><p class="sub">상승률 상위 30종목 중 같은 테마로 묶인 종목이 많은 순</p>' + wide(["테마", "상위30 안", "대장주", "등락", "2등주", "등락"], rows, right=(1, 3, 5))
        rows = [[chip(x["name"], False), num(x["avg"]), str(x["up5"]), str(x["n"]), f'<b>{E(x["lead"])}</b>', num(x["lead_ret"], 1), E(x["second"]), num(x["second_ret"], 1)] for x in mk.get("themes", [])]
        body += '<h2>테마별 상승률 TOP</h2><p class="sub">테마 안 종목들의 평균 등락률 (5종목 이상 테마)</p>' + wide(["테마", "평균", "5%↑", "종목 수", "주도주", "등락", "2등주", "등락"], rows, right=(1, 2, 3, 5, 7))
        rows = [[chip(x["name"], False), num(x["avg"]), str(x["n"]), E(x["lead"]), num(x["lead_ret"], 1)] for x in mk.get("themes_worst", [])]
        body += "<h3>많이 내린 테마</h3>" + wide(["테마", "평균", "종목 수", "그나마 강한 종목", "등락"], rows, right=(1, 2, 4))
    else:
        body += '<p class="empty">이날 지수·테마 기록 없음</p>'
    body += '<h2>대장주</h2><p class="sub">+10% 이상·거래대금 100억 이상, 거래대금 순. 이름 앞 색 막대가 테마 색이에요.</p>' + leaders_table(lead, d, mk)
    return page(fmt_d(d) + " 시장", "코스피·코스닥, 테마, 대장주", body, depth=1)


MARKET_JS = r"""
(() => {
const D = JSON.parse(document.getElementById('mdata').textContent);
const app = document.getElementById('mapp'); if (!app || !D.length) return;
const WD = '일월화수목금토';
const ymd = (x) => x.getUTCFullYear() + String(x.getUTCMonth() + 1).padStart(2, '0') + String(x.getUTCDate()).padStart(2, '0');
const P = (s) => new Date(Date.UTC(+s.slice(0, 4), +s.slice(4, 6) - 1, +s.slice(6, 8)));
const fd = (s, w) => { const x = P(s); return (x.getUTCMonth() + 1) + '/' + x.getUTCDate() + (w ? '(' + WD[x.getUTCDay()] + ')' : ''); };
const pct = (v, nd = 1) => v == null ? '–' : `<span class="${v > 0 ? 'up' : v < 0 ? 'dn' : ''}">${v > 0 ? '+' : ''}${v.toFixed(nd)}%</span>`;
const tint = (v) => v == null ? '' : `background:color-mix(in srgb,var(${v > 0 ? '--up' : '--dn'}) ${Math.round(Math.min(Math.abs(v) / 4, 1) * 30 + 6)}%,var(--bg))`;
const esc = (t) => String(t ?? '').replace(/[&<>"]/g, (c) => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;'}[c]));
const chip = (t, c, full) => t ? `<span class="chip" style="--c:${c}" title="${esc(full || t)}">${esc(t)}</span>` : '';
let mode = 'month', anchor = D[D.length - 1].d, from = D[0].d, to = anchor;
try { const h = location.hash.slice(1); if (['day','week','month','quarter','half','year'].includes(h)) mode = h; } catch (e) {}

function range() {
  const x = P(anchor), y = x.getUTCFullYear(), m = x.getUTCMonth();
  if (mode === 'day') return [anchor, anchor];
  if (mode === 'week') { const dw = (x.getUTCDay() + 6) % 7; const s = new Date(x - dw * 864e5); return [ymd(s), ymd(new Date(+s + 4 * 864e5))]; }
  if (mode === 'month') return [ymd(new Date(Date.UTC(y, m, 1))), ymd(new Date(Date.UTC(y, m + 1, 0)))];
  if (mode === 'quarter') { const q = Math.floor(m / 3) * 3; return [ymd(new Date(Date.UTC(y, q, 1))), ymd(new Date(Date.UTC(y, q + 3, 0)))]; }
  if (mode === 'half') { const h = m < 6 ? 0 : 6; return [ymd(new Date(Date.UTC(y, h, 1))), ymd(new Date(Date.UTC(y, h + 6, 0)))]; }
  if (mode === 'year') return [y + '0101', y + '1231'];
  return [from, to];
}
function label(r) {
  const x = P(anchor), y = x.getUTCFullYear(), m = x.getUTCMonth();
  return ({day: `${y}년 ${fd(anchor, true)}`, week: `${fd(r[0])} ~ ${fd(r[1])} 주`, month: `${y}년 ${m + 1}월`, quarter: `${y}년 ${Math.floor(m / 3) + 1}분기`,
           half: `${y}년 ${m < 6 ? '상' : '하'}반기`, year: `${y}년`, custom: `직접 고른 기간`})[mode];
}
function shift(dir) {
  if (mode === 'custom') return;
  if (mode === 'day') { const i = D.findIndex((r) => r.d === anchor); const j = Math.min(D.length - 1, Math.max(0, (i < 0 ? D.length - 1 : i) + dir)); anchor = D[j].d; return; }
  const x = P(anchor);
  if (mode === 'week') anchor = ymd(new Date(+x + dir * 7 * 864e5));
  else { const k = {month: 1, quarter: 3, half: 6, year: 12}[mode]; anchor = ymd(new Date(Date.UTC(x.getUTCFullYear(), x.getUTCMonth() + dir * k, 1))); }
}
function grid(rows, r) {
  const by = Object.fromEntries(rows.map((z) => [z.d, z]));
  const s = P(r[0]), e = P(r[1]);
  let cur = new Date(+s - ((s.getUTCDay() + 6) % 7) * 864e5), html = '';
  const span = (e - s) / 864e5;
  if (span <= 40) {
    html = '<div class="cal cal5">' + [...'월화수목금'].map((w) => `<div class="cal-h">${w}</div>`).join('');
    while (cur <= e) {
      const wk = [0, 1, 2, 3, 4].map((i) => ymd(new Date(+cur + i * 864e5)));
      if (!wk.some((d) => d >= r[0] && d <= r[1])) { cur = new Date(+cur + 7 * 864e5); continue; }
      for (let i = 0; i < 5; i++) {
        const d = ymd(new Date(+cur + i * 864e5)), z = by[d], inR = d >= r[0] && d <= r[1];
        if (!inR) html += '<div class="cal-d off"></div>';
        else if (z) html += `<a class="cal-d" href="m/${d}.html" style="${tint(z.avg)}"><b>${+d.slice(6)}</b><span>코 ${pct(z.k)}</span><span>닥 ${pct(z.q)}</span>${chip(z.ts, z.c, z.t)}</a>`;
        else html += `<div class="cal-d none"><b>${+d.slice(6)}</b></div>`;
      }
      cur = new Date(+cur + 7 * 864e5);
    }
    return html + '</div>';
  }
  // 긴 기간: 한 칸 = 하루, 세로 5칸(월~금) × 가로 주
  let cols = '', lastM = -1, months = '';
  while (cur <= e) {
    let col = '';
    const fi = [0, 1, 2, 3, 4].map((i) => ymd(new Date(+cur + i * 864e5))).find((d) => d >= r[0] && d <= r[1]) || ymd(cur);
    const mm = P(fi).getUTCMonth();
    months += `<span>${mm !== lastM ? (mm + 1) + '월' : ''}</span>`; lastM = mm;
    for (let i = 0; i < 5; i++) {
      const d = ymd(new Date(+cur + i * 864e5)), z = by[d];
      const inR = d >= r[0] && d <= r[1];
      col += !inR ? '<i class="x"></i>' : z ? `<a href="m/${d}.html" style="${tint(z.avg)}" title="${fd(d, true)} 코스피 ${z.k}% · 코스닥 ${z.q}% · ${esc(z.ts)}"></a>` : '<i></i>';
    }
    cols += `<div class="hc">${col}</div>`;
    cur = new Date(+cur + 7 * 864e5);
  }
  return `<div class="heat"><div class="hm">${months}</div><div class="hg">${cols}</div></div><p class="sub">칸 하나가 하루예요(세로 월~금). 빨강은 오른 날, 파랑은 내린 날, 진할수록 많이 움직인 날. 누르면 그날 시장 페이지로 가요.</p>`;
}
function themeFlow(rows, r) {
  const span = (P(r[1]) - P(r[0])) / 864e5;
  if (span < 13) return '';
  const byMonth = span > 62;
  const key = (d) => byMonth ? d.slice(0, 6) : ymd(new Date(+P(d) - ((P(d).getUTCDay() + 6) % 7) * 864e5));
  const cols = [...new Set(rows.map((z) => key(z.d)))];
  const cnt = {}, tot = {};
  rows.forEach((z) => { if (!z.t) return; (cnt[z.t] = cnt[z.t] || {})[key(z.d)] = (cnt[z.t][key(z.d)] || 0) + 1; tot[z.t] = (tot[z.t] || 0) + 1; });
  const top = Object.keys(tot).sort((a, b) => tot[b] - tot[a]).slice(0, 8);
  if (!top.length) return '';
  const meta = Object.fromEntries(rows.map((z) => [z.t, z]));
  const mx = Math.max(...top.flatMap((t) => cols.map((c) => cnt[t][c] || 0)));
  const head = cols.map((c) => `<th class="r">${byMonth ? (+c.slice(4)) + '월' : fd(c)}</th>`).join('');
  const body = top.map((t) => `<tr><td>${chip(meta[t].ts, meta[t].c, t)}</td>` + cols.map((c) => { const v = cnt[t][c] || 0;
    return `<td class="r" style="${v ? `background:color-mix(in srgb,${meta[t].c} ${Math.round(v / mx * 55 + 10)}%,transparent)` : ''}">${v || ''}</td>`; }).join('') + `<td class="r"><b>${tot[t]}</b></td></tr>`).join('');
  return `<h3>테마 흐름 (${byMonth ? '달' : '주'}별 1등 횟수)</h3><p class="sub">어느 테마가 언제 시장을 이끌었고 언제 바뀌었는지 보여요. 색이 진할수록 그 ${byMonth ? '달' : '주'}에 1등을 많이 한 테마예요.</p>`
    + `<div class="scroll"><table class="wide flow"><thead><tr><th>테마</th>${head}<th class="r">합계</th></tr></thead><tbody>${body}</tbody></table></div>`;
}
const IX = JSON.parse(document.getElementById('idata').textContent);
const TM = JSON.parse(document.getElementById('tdata').textContent), THS = TM.s, THC = TM.c;
function ixChart(key, label, r) {
  const S = IX[key]; if (!S || !S.length) return '';
  const ma = S.map((z, i) => i >= 19 ? S.slice(i - 19, i + 1).reduce((a, b) => a + b.c, 0) / 20 : null);
  let i1 = S.findIndex((z) => z.d >= r[0]); let i2 = S.map((z) => z.d <= r[1]).lastIndexOf(true);
  if (i1 < 0 || i2 < 0 || i2 < i1) return '';
  const hl = [i1, i2];
  if (i2 - i1 < 39) i1 = Math.max(0, i2 - 39);
  const X = S.slice(i1, i2 + 1), M = ma.slice(i1, i2 + 1);
  const W = 640, H = 250, L = 52, R = 10, T = 10, PH = 150, VH = 50, B = 22, m = X.length, bw = (W - L - R) / m;
  const vals = X.map((z) => z.c).concat(M.filter((v) => v != null));
  let lo = Math.min(...vals), hi = Math.max(...vals); const pad = (hi - lo) * .06 || 1; lo -= pad; hi += pad;
  const xx = (i) => L + bw * (i + .5), yy = (v) => T + PH * (hi - v) / (hi - lo), vmax = Math.max(...X.map((z) => z.v)) || 1, VY0 = T + PH + 10 + VH;
  let g = '';
  X.forEach((z, i) => { if (M[i] != null && z.c < M[i]) g += `<rect x="${(L + bw * i).toFixed(1)}" y="${T}" width="${bw.toFixed(1)}" height="${PH}" class="below"/>`; });
  if (hl[0] > i1) g += `<rect x="${L}" y="${T}" width="${(bw * (hl[0] - i1)).toFixed(1)}" height="${PH + 10 + VH}" fill="var(--bg)" opacity=".55"/>`;
  for (let k = 0; k < 4; k++) { const v = lo + (hi - lo) * k / 3; g += `<line x1="${L}" x2="${W - R}" y1="${yy(v).toFixed(1)}" y2="${yy(v).toFixed(1)}" class="grid"/><text x="${L - 6}" y="${(yy(v) + 4).toFixed(1)}" text-anchor="end">${Math.round(v).toLocaleString()}</text>`; }
  g += `<path d="${M.map((v, i) => v == null ? '' : `${i && M[i - 1] != null ? 'L' : 'M'}${xx(i).toFixed(1)},${yy(v).toFixed(1)}`).join(' ')}" fill="none" stroke="var(--mute)" stroke-width="1.6" stroke-dasharray="5 4"/>`;
  g += `<path d="${X.map((z, i) => `${i ? 'L' : 'M'}${xx(i).toFixed(1)},${yy(z.c).toFixed(1)}`).join(' ')}" fill="none" stroke="var(--ink)" stroke-width="2"/>`;
  X.forEach((z, i) => { const up = i === 0 ? true : z.c >= X[i - 1].c, h = VH * z.v / vmax;
    g += `<rect x="${(L + bw * i + bw * .15).toFixed(1)}" y="${(VY0 - h).toFixed(1)}" width="${Math.max(.6, bw * .7).toFixed(1)}" height="${Math.max(1, h).toFixed(1)}" fill="var(${up ? '--up' : '--dn'})" opacity=".55"><title>${fd(z.d, true)} ${label} ${z.c.toLocaleString()}</title></rect>`; });
  const step = Math.max(1, Math.floor(m / 6));
  for (let i = 0; i < m; i += step) g += `<text x="${xx(i).toFixed(1)}" y="${H - 4}" text-anchor="middle">${m > 300 ? X[i].d.slice(2, 4) + '.' + (+X[i].d.slice(4, 6)) : fd(X[i].d)}</text>`;
  const a = S[hl[0] - 1] || S[hl[0]], b = S[hl[1]], gap = ma[hl[1]] ? (b.c / ma[hl[1]] - 1) * 100 : null;
  return `<h3>${label} <b>${b.c.toLocaleString()}</b> ${pct((b.c / a.c - 1) * 100)} <small>기간 · 20일선 ${gap == null ? '–' : pct(gap) + (gap > 0 ? ' 위' : ' 아래')}</small></h3><div class="chart"><svg viewBox="0 0 ${W} ${H}">${g}</svg></div>`;
}
// 이 기간 가장 세게 오른 종목: 기간 안에 대장주였던 종목의 '기간 등락률' (기간 시작 전날 종가 → 기간 마지막 종가)
const PX = {};
const loadPx = (y) => PX[y] || (PX[y] = fetch(`px/${y}.json`).then((r) => r.ok ? r.json() : null).catch(() => null));
let bestTok = 0;
async function periodBest(rows, r) {
  const tok = ++bestTok, box = () => document.getElementById('bestbox');
  const cand = {};
  rows.forEach((z) => (z.ls || []).forEach(([n, rr, th, c]) => { if (!c) return; const f = (cand[c] = cand[c] || {n, th, k: 0, first: z.d}); f.k++; if (th) f.th = th; }));
  if (!Object.keys(cand).length) return;
  if (box()) box().innerHTML = '<h3>이 기간 가장 세게 오른 종목</h3><p class="sub">불러오는 중…</p>';
  const y0 = +r[0].slice(0, 4), y1 = +r[1].slice(0, 4), ys = [];
  for (let y = y0 - 1; y <= y1; y++) ys.push(y);
  const files = (await Promise.all(ys.map(loadPx))).filter(Boolean);
  if (tok !== bestTok || !box()) return;
  const res = [];
  Object.entries(cand).forEach(([c, f]) => {
    let base = null, last = null, hi = null, lastD = null;
    files.forEach((F) => { const p = F.p[c]; if (!p) return; F.d.forEach((d, i) => { const v = p[i]; if (v == null) return;
      if (d < r[0]) base = v; else if (d <= r[1]) { if (base == null) base = v; last = v; lastD = d; hi = Math.max(hi ?? v, v); } }); });
    if (base && last) res.push({c, ...f, ret: (last / base - 1) * 100, hi: (hi / base - 1) * 100, lastD});
  });
  if (!res.length) { box().innerHTML = ''; return; }
  res.sort((a, b) => b.ret - a.ret);
  const th = (t) => t ? chip(THS[t] || t.split('(')[0].replace(/ /g, '').slice(0, 6), THC[t] || '#8a959c', t) : '';
  box().innerHTML = '<h3>이 기간 가장 세게 오른 종목</h3><p class="sub">이 기간에 대장주(+10%↑·거래대금 100억↑)로 한 번이라도 뜬 종목을, 기간 시작 전날 종가부터 기간 마지막 날 종가까지 오른 비율로 줄 세웠어요. 고점은 기간 중 가장 높았던 종가 기준이에요.</p>'
    + '<div class="scroll"><table class="wide"><thead><tr><th>종목</th><th class="r">기간 등락</th><th class="r">고점까지</th></tr></thead><tbody>' + res.slice(0, 10).map((z) =>
      `<tr><td><b>${esc(z.n)}</b><small class="k">${th(z.th)} · 대장주 ${z.k}회 · 처음 ${fd(z.first)}</small></td><td class="r"><b>${pct(z.ret)}</b></td><td class="r">${pct(z.hi)}</td></tr>`).join('')
    + '</tbody></table></div>';
}
function render() {
  const r = range(), rows = D.filter((z) => z.d >= r[0] && z.d <= r[1]);
  const ic = document.getElementById('ichart');
  const fy = (d) => d.slice(0, 4) + '.' + (+d.slice(4, 6)) + '.' + (+d.slice(6));
  const pl = document.getElementById('plabel');
  if (pl) pl.innerHTML = `${label(r)}<small>${fy(r[0])} ~ ${fy(r[1])}${rows.length ? ` · 거래일 ${rows.length}일` : ''}</small>`;
  if (ic) ic.innerHTML = '<div class="legend"><span><i style="background:var(--ink)"></i>지수</span><span><i style="background:var(--mute)"></i>20일선(점선)</span><span><i style="background:color-mix(in srgb,var(--dn) 25%,transparent)"></i>20일선 아래</span><span><i style="background:var(--up)"></i>거래량</span></div>' + ixChart('KOSPI', '코스피', r) + ixChart('KOSDAQ', '코스닥', r);
  const comp = (k) => rows.length ? (rows.reduce((a, z) => a * (1 + (z[k] || 0) / 100), 1) - 1) * 100 : null;
  const up = rows.filter((z) => z.k > 0).length, dn = rows.filter((z) => z.k < 0).length;
  const cnt = {}; rows.forEach((z) => { if (z.t) cnt[z.t] = (cnt[z.t] || 0) + 1; });
  const tops = Object.entries(cnt).sort((a, b) => b[1] - a[1]);
  const meta = Object.fromEntries(rows.map((z) => [z.t, z]));
  let h = '';
  if (!rows.length) { app.querySelector('.out').innerHTML = h + '<p class="empty">이 기간에는 기록이 없어요.</p>'; return; }
  h += `<div class="kpis"><div><b>${pct(comp('k'))}</b><span>코스피 기간 등락</span></div><div><b>${pct(comp('q'))}</b><span>코스닥 기간 등락</span></div>`
    + `<div><b>${rows.length}일</b><span>거래일 · 코스피 오른 날 <span class="up">${up}</span> / 내린 날 <span class="dn">${dn}</span></span></div>`
    + `<div><b>${tops.length ? chip(meta[tops[0][0]].ts, meta[tops[0][0]].c, tops[0][0]) : '–'}</b><span>가장 많이 1등 한 테마${tops.length ? ' (' + tops[0][1] + '회)' : ''}</span></div></div>`;
  if (mode === 'day') {
    const z = rows[0];
    h += `<p><a class="go" href="m/${z.d}.html">이날 테마별 상승률·대장주 전체 보기 ›</a></p>`;
  }
  h += grid(rows, r);
  if (tops.length && mode !== 'day') {
    const mx = tops[0][1];
    h += '<h3>1등 테마가 된 횟수</h3><div class="bars">' + tops.slice(0, 12).map(([t, n]) => `<div class="bar-row"><span class="bl">${chip(meta[t].ts, meta[t].c, t)}</span><span class="bt"><i style="width:${n / mx * 100}%;background:${meta[t].c}"></i></span><b>${n}회</b></div>`).join('') + '</div>';
  }
  h += themeFlow(rows, r);
  if (mode !== 'day') h += '<div id="bestbox"></div>';
  if (mode !== 'day') {
    const fq = {};
    rows.forEach((z) => (z.ls || []).forEach(([n, rr, th]) => { if (!n) return; const f = (fq[n] = fq[n] || {n: 0, s: 0, th, last: z.d}); f.n++; f.s += rr; f.last = z.d; if (th) f.th = th; }));
    const top = Object.entries(fq).filter(([, f]) => f.n >= 2).sort((a, b) => b[1].n - a[1].n || b[1].s - a[1].s).slice(0, 10);
    if (top.length) {
      const cmap = Object.fromEntries(rows.flatMap((z) => (z.ls || []).map(([n, , th]) => [th, z])));
      h += '<h3>이 기간 자주 오른 종목</h3><p class="sub">대장주(+10%↑·거래대금 100억↑)에 이름을 올린 횟수 순이에요. 여러 번 오른 종목은 그 기간 시장이 계속 찾은 종목이에요.</p>'
        + '<div class="scroll"><table class="wide"><tbody>' + top.map(([n, f]) => { const th = f.th, ts = th ? (THS[th] || th.split('(')[0].replace(/ /g, '').slice(0, 6)) : '';
          return `<tr><td><b>${esc(n)}</b><small class="k">${chip(ts, THC[th] || '#8a959c', th)} · 마지막 ${fd(f.last)}</small></td><td class="r"><b>${f.n}회</b><small class="k">평균 ${pct(f.s / f.n)}</small></td></tr>`; }).join('') + '</tbody></table></div>';
    }
  }
  app.querySelector('.out').innerHTML = h;
  if (mode !== 'day') periodBest(rows, r);
  app.querySelectorAll('.pmode a').forEach((a) => a.classList.toggle('on', a.dataset.m === mode));
  app.querySelector('.custom').hidden = mode !== 'custom';
  app.querySelectorAll('.pnav').forEach((b) => b.disabled = mode === 'custom');
}
app.querySelectorAll('.pmode a').forEach((a) => a.addEventListener('click', (e) => { e.preventDefault();
  if (a.dataset.m === 'custom' && mode !== 'custom') { const r = range(); from = r[0]; to = r[1] > D[D.length - 1].d ? D[D.length - 1].d : r[1]; if (window._setSel) window._setSel(); }
  mode = a.dataset.m; if (mode !== 'custom') anchor = D[D.length - 1].d; render(); }));
app.querySelector('.prev').addEventListener('click', () => { shift(-1); render(); });
app.querySelector('.next').addEventListener('click', () => { shift(1); render(); });
// 직접 고르기: 년·월·일을 따로 골라요 (달력을 넘길 필요 없이 년도 바로 선택)
const first = ((IX.KOSPI || [])[0] || D[0]).d < D[0].d ? IX.KOSPI[0].d : D[0].d, last = D[D.length - 1].d;
const p2 = (n) => String(n).padStart(2, '0');
function fillSel(box, val) {
  const sy = box.querySelector('.y'), sm = box.querySelector('.m'), sd = box.querySelector('.d');
  const y0 = +first.slice(0, 4), y1 = +last.slice(0, 4);
  sy.innerHTML = Array.from({length: y1 - y0 + 1}, (_, i) => y1 - i).map((y) => `<option value="${y}">${y}년</option>`).join('');
  sm.innerHTML = Array.from({length: 12}, (_, i) => `<option value="${p2(i + 1)}">${i + 1}월</option>`).join('');
  const setDays = () => { const n = new Date(Date.UTC(+sy.value, +sm.value, 0)).getUTCDate(), keep = Math.min(+sd.value || 1, n);
    sd.innerHTML = Array.from({length: n}, (_, i) => `<option value="${p2(i + 1)}">${i + 1}일</option>`).join(''); sd.value = p2(keep); };
  box._set = (v) => { sy.value = v.slice(0, 4); sm.value = v.slice(4, 6); sd.value = v.slice(6); setDays(); sd.value = v.slice(6); };
  box._set(val);
  sy.addEventListener('change', () => { setDays(); setC(); }); sm.addEventListener('change', () => { setDays(); setC(); }); sd.addEventListener('change', setC);
}
const getSel = (box) => box.querySelector('.y').value + box.querySelector('.m').value + box.querySelector('.d').value;
const b1 = app.querySelector('#f1'), b2 = app.querySelector('#f2');
const setC = () => { from = getSel(b1); to = getSel(b2); if (from > to) [from, to] = [to, from]; render(); };
fillSel(b1, from); fillSel(b2, to);
window._setSel = () => { b1._set(from); b2._set(to); };
render();
})();
"""


def md_get(code, n=1900):
    """네이버 지수 일봉 (종가·거래량)"""
    import market_data as md
    t = md.S.get(f"https://fchart.stock.naver.com/sise.nhn?symbol={code}&timeframe=day&count={n}&requestType=0", timeout=30).text
    return [dict(d=r[0], c=round(float(r[4]), 2), v=float(r[5])) for r in md._items(t)]


def market_page(days, lead):
    rows = []
    ld = {}
    if len(lead):
        for r in lead.sort_values("value", ascending=False).itertuples():
            ld.setdefault(r.date, r)
    for d in sorted(days):
        mk = market(d)
        if not mk:
            continue
        k, q = fnum(mk.get("kospi")), fnum(mk.get("kosdaq"))
        hot = ((mk.get("hot") or mk.get("themes") or [{}])[0]).get("name", "")
        lr = (mk.get("leaders") or [{}])[0]
        lt = lr.get("theme") or ""
        rows.append(dict(d=d, k=k, q=q, avg=round(((k or 0) + (q or 0)) / 2, 2), t=hot, ts=short_theme(hot) if hot else "", c=color(hot) if hot else "",
                         l=lr.get("name", ""), lr=fnum(lr.get("ret")) or 0, lt=lt, lts=short_theme(lt) if lt else "", lc=color(lt),
                         ls=[[x.get("name", ""), fnum(x.get("ret")) or 0, x.get("theme") or "", str(x.get("code") or "")] for x in (mk.get("leaders") or [])]))
    data = json.dumps(rows, ensure_ascii=False).replace("</", "<\\/")
    allth = {x[2] for r in rows for x in r["ls"] if x[2]}
    thmap = json.dumps({"s": {t: short_theme(t) for t in allth}, "c": {t: color(t) for t in allth}}, ensure_ascii=False)
    ix = {}
    try:
        for k in ("KOSPI", "KOSDAQ"):
            t_ = md_get(k)
            ix[k] = t_
    except Exception as e:
        print("지수 받기 실패:", e)
    idata = json.dumps(ix, ensure_ascii=False)
    body = ('<div id="mapp"><div class="pbar"><nav class="tabs pmode">'
             + "".join(f'<a href="#{m}" data-m="{m}">{n}</a>' for m, n in (("day", "일"), ("week", "주"), ("month", "월"), ("quarter", "분기"), ("half", "반기"), ("year", "년"), ("custom", "직접")))
             + '</nav><div class="pnavs"><button class="pnav prev" aria-label="이전">‹ 이전</button><button class="pnav next" aria-label="다음">다음 ›</button></div>'
             '<div class="custom" hidden>'
             + "".join(f'<div class="dsel" id="{k}"><span>{n}</span><select class="y" aria-label="{n} 년"></select><select class="m" aria-label="{n} 월"></select><select class="d" aria-label="{n} 일"></select></div>' for k, n in (("f1", "시작"), ("f2", "끝")))
             + '</div></div>'
             '<h2 class="plabel" id="plabel"></h2><div id="ichart"></div><p class="sub">고른 기간에 맞춰 지수가 다시 그려져요. 기간이 짧으면 앞 40거래일을 흐리게 같이 보여줘요.</p><div class="out"></div></div>')
    body += f'<script type="application/json" id="mdata">{data}</script><script type="application/json" id="idata">{idata}</script><script type="application/json" id="tdata">{thmap}</script><script>{MARKET_JS}</script>'
    return page("대장주 달력", "기간을 골라 시장·테마 흐름 보기", body, "대장주 달력")


def week_page(mon, days, t, fm, lead, vi, expect):
    end = (dt.datetime.strptime(mon, "%Y%m%d") + dt.timedelta(days=4)).strftime("%Y%m%d")
    wk = [d for d in days if mon <= d <= end]
    tw = t[(t["판 날"].astype(str).str.replace("-", "") >= mon) & (t["판 날"].astype(str).str.replace("-", "") <= end)] if len(t) else t
    body = '<div class="cal cal5">' + "".join(f'<div class="cal-h">{w}</div>' for w in "월화수목금")
    for i in range(5):
        d = (dt.datetime.strptime(mon, "%Y%m%d") + dt.timedelta(days=i)).strftime("%Y%m%d")
        v = mkt_tint(d)
        st = f' style="background:color-mix(in srgb,var({"--up" if v > 0 else "--dn"}) {min(abs(v) / 4, 1) * 30 + 6:.0f}%,var(--bg))"' if v is not None else ""
        body += (f'<a class="cal-d" href="../d/{d}.html"{st}><b>{int(d[6:])}</b>{market_cell(d, lead)}{alert_cell(d, t)}</a>' if d in wk else f'<div class="cal-d none"><b>{int(d[6:])}</b></div>')
    body += "</div>"
    body += "<h2>단계별 이번 주 성적</h2>" + strat_rows(tw, expect, with_expect=False)
    lw = lead[(lead.date >= mon) & (lead.date <= end)] if len(lead) else lead
    body += "<h2>대장주는 다음날도 올랐나</h2>"
    if len(lw):
        nc = pd.to_numeric(lw["next_close"], errors="coerce").dropna() if "next_close" in lw else pd.Series(dtype=float)
        if len(nc):
            body += f'<p class="kpi">다음날 결과가 나온 {len(nc)}종목 중 {int((nc > 0).sum())}종목 상승 · 다음날 종가 평균 {num(nc.mean(), 1)}</p>'
        rows = []
        for r in lw.sort_values("date").itertuples():
            th = theme_of(r, market(r.date))
            rows.append([f'<span class="bar" style="--c:{color(th)}"></span><b>{E(r.name)}</b><small class="k">{fmt_d(r.date, False)} {chip(th)}</small>', num(r.ret, 1),
                         num(getattr(r, "next_close", None), 1), num(getattr(r, "next_open", None), 1), E(r.reason)])
        body += wide(["종목", "그날", "다음날 종가", "다음날 시가", "오른 이유 후보"], rows, right=(1, 2, 3))
    else:
        body += '<p class="empty">기록 없음</p>'
    body += '<h2>초단타 · VI 단타 자동 복기 <span class="badge test">테스트 중</span></h2>' + vi_table(vi, wk)
    body += f'<h2>초단타 · {M15} 모의 <span class="badge test">테스트 중</span></h2>' + m15_table(fm, wk)
    body += "<h2>이번 주 끝난 매매 (전체)</h2>" + trades_wide(tw)
    x = dt.datetime.strptime(mon, "%Y%m%d")
    return page(f"{x.month}월 {x.day}일 주간 복기", f"{fmt_d(mon)} ~ {fmt_d(end)}", body, depth=1)


def main():
    t, h, fm, lead, vi, expect = load()
    days = all_dates(t, fm, lead, vi)
    import shutil
    for sub in ("d", "w", "m"):
        shutil.rmtree(os.path.join(OUT, sub), ignore_errors=True)
        os.makedirs(os.path.join(OUT, sub), exist_ok=True)
    open(os.path.join(OUT, ".nojekyll"), "w").close()
    W = lambda p, txt: open(os.path.join(OUT, p), "w", encoding="utf-8").write(txt)
    # 알림·매매 기록이 있는 날만 일별 알림 페이지, 시장 페이지는 모든 날
    sold = {str(x).replace("-", "") for x in t["판 날"].dropna()} if len(t) else set()
    own = {d for d in days if messages(d) or d in sold or (len(fm) and (fm.date == d).any()) or (len(vi) and (vi.date == d).any())}
    HAS_D.update(own)
    recent = {d for d in days if d >= "20261102"} | own
    for d in days:
        if d in own or d in recent:
            W(f"d/{d}.html", day_page(d, t, fm, lead, vi))
        W(f"m/{d}.html", market_page_day(d, lead))
    for m in sorted({monday(d) for d in days}):
        W(f"w/{m}.html", week_page(m, days, t, fm, lead, vi, expect))
    W("index.html", index_page(days, t, h, fm, vi, expect))
    W("market.html", market_page(days, lead))
    shutil.copy(os.path.join(ROOT, "tools", "live.js"), os.path.join(OUT, "live.js"))
    W("flow.html", page("장중 흐름", "30분마다 데스크톱 봇이 올린 테마·대장주·상한가·돈 급증", '<div class="flow"><p class="empty">불러오는 중…</p></div><script src="live.js" defer></script>'))
    print(f"페이지 만듦: 날짜 {len(days)}일, 주 {len({monday(d) for d in days})}개 → {OUT}")


if __name__ == "__main__":
    main()
