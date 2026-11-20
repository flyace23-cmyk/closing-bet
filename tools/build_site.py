"""알림장 웹페이지 만들기 (GitHub Pages: docs 폴더)

  index.html        첫 화면: 매매법별 누적 성적(단계별, 한 줄씩), 진행 중 종목(한 줄씩), 알림 달력, 최근 알림
  market.html       대장주 달력: 날짜마다 코스피·코스닥 등락과 1등 테마
  d/날짜.html       하루치 알림: 보낸 알림 원문(봇 + 노트북 VI봇), 대장주, VI 복기, 15분봉 단타 모의, 끝난 매매
  m/날짜.html       하루치 시장: 지수, 오른·내린 종목 수, 테마별 상승률, 대장주(테마 색)
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
WD = "월화수목금토일"
M15 = "15분봉 MACD·일목 단타"

# 단계: 보유 기간으로 나눔
STAGE = {"VI 단타": "초단타", M15: "초단타", "종가베팅": "단타", "저가매수": "스윙", "스윙 A": "스윙", "중기 스윙": "중기 스윙"}
STAGE_ORDER = ["초단타", "단타", "스윙", "중기 스윙"]
STAGE_NOTE = {"초단타": "장중", "단타": "하룻밤", "스윙": "며칠~몇 주", "중기 스윙": "몇 주~몇 달"}
SHOW_NAME = {"중기 스윙": "CAN SLIM"}
EXPECT_M15 = (27, -0.41)   # 1년 검증 (15분봉, 288종목)
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
    t = theme.split("(")[0].strip() if short and len(theme) > 10 else theme
    return f'<span class="chip" style="--c:{color(theme)}">{E(t)}</span>'


def read(path):
    return pd.read_csv(path, dtype={"code": str, "date": str, "종목코드": str}) if os.path.exists(path) and os.path.getsize(path) else pd.DataFrame()


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
        add = pd.DataFrame({"매매법": M15, "구분": "모의", "종목": fm.name, "산 날": fm.date.map(ymd), "판 날": fm.date.map(ymd),
                            "수익률(%)": fm.ret.round(2), "메모": fm.why})
        t = pd.concat([t, add], ignore_index=True)
    lead = read(os.path.join(REC, "leaders.csv"))
    vi = read(os.path.join(VI, "review.csv"))
    if len(vi):
        vi["date"] = vi["날짜"].str.replace("-", "")
    return t, h, fm, lead, vi, expect


def all_dates(t, fm, lead, vi):
    ds = set()
    for f in glob.glob(os.path.join(REC, "messages", "*.jsonl")) + glob.glob(os.path.join(VI, "messages", "*.jsonl")) + glob.glob(os.path.join(REC, "market", "*.json")):
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
def strat_rows(t, expect, with_expect=True):
    """단계 → 매매법 → 구분, 한 줄씩"""
    keys = [k for k, _ in t.groupby(["매매법", "구분"], sort=False)] if len(t) else []
    for k in list(expect.keys()) + [(M15, "모의"), ("VI 단타", "자동 복기(정식 시간)")]:
        if k not in keys:
            keys.append(k)
    keys = sorted([k for k in keys if k[0] in STAGE], key=lambda k: (STAGE_ORDER.index(STAGE[k[0]]), k[0], k[1]))
    rows, last = [], None
    for s, k in keys:
        g = t[(t.매매법 == s) & (t.구분 == k)] if len(t) else t
        n, w, a = stat(g["수익률(%)"] if len(g) else [])
        e = expect.get((s, k)) or (EXPECT_M15 if s == M15 else (None, None))
        stage = STAGE[s]
        if stage != last:
            rows.append(("group", f"<b>{stage}</b> <small>{STAGE_NOTE[stage]}</small>"))
            last = stage
        cells = [f"<b>{E(SHOW_NAME.get(s, s))}</b>", E(k), str(n), f"{w:.0f}%" if w is not None else "–", num(a)]
        if with_expect:
            cells += [f"{e[0]}%" if e[0] is not None else "–", num(e[1]) if e[1] is not None else "–"]
        rows.append(cells)
    head = ["매매법", "구분", "건수", "승률", "평균"] + (["기대 승률", "기대 평균"] if with_expect else [])
    return wide(head, rows, right=(2, 3, 4, 5, 6))


def holdings(h):
    if not len(h):
        return '<p class="empty">진행 중인 종목 없음</p>'
    rows = []
    for r in h.to_dict("records"):
        s = r["매매법"].split("(")[0]
        rows.append([f"<b>{E(r['종목'])}</b>", E(STAGE.get(s, "")), E(SHOW_NAME.get(s, r["매매법"])), E(r["시작일"]), E(r["상태"]),
                     f'{fnum(r["평단"]):,.0f}' if fnum(r["평단"]) else "–", f'{fnum(r.get("현재가")):,.0f}' if fnum(r.get("현재가")) else "–",
                     num(r.get("수익률(%)"))])
    return wide(["종목", "단계", "매매법", "시작일", "상태", "평단", "현재가", "수익률"], rows, right=(5, 6, 7))


def leaders_table(lead, d, mk):
    x = lead[lead.date == d] if len(lead) else lead
    if not len(x):
        return '<p class="empty">대장주 기록 없음</p>'
    rows = []
    for r in x.itertuples():
        th = theme_of(r, mk)
        rows.append([f'<span class="bar" style="--c:{color(th)}"></span><b>{E(r.name)}</b>', chip(th), num(r.ret, 1),
                     f"{fnum(r.value):,.0f}억", num(getattr(r, "next_open", None), 1), num(getattr(r, "next_close", None), 1), E(r.reason)])
    return wide(["종목", "테마", "그날", "거래대금", "다음날 시가", "다음날 종가", "오른 이유 후보"], rows, right=(2, 3, 4, 5))


def m15_table(fm, ds):
    x = fm[fm.date.isin(ds)] if len(fm) else fm
    if not len(x):
        return '<p class="empty">신호 없음</p>'
    n, w, a = stat(x.ret)
    rows = [[f"<b>{E(r.name)}</b>", fmt_d(r.date, False), f"{int(r.t_in) // 100:02d}:{int(r.t_in) % 100:02d} → {int(r.t_out) // 100:02d}:{int(r.t_out) % 100:02d}",
             f"{r.buy:,.0f}", f"{r.sell:,.0f}", num(r.ret), E(r.why)] for r in x.itertuples()]
    return (f'<p class="kpi">{n}건 · 승률 {w:.0f}% · 평균 {num(a)} <small>1건 100만원, 비용 0.35% 뺌 · 1년 검증 기대 -0.41%</small></p>'
            + wide(["종목", "날짜", "시간", "매수가", "매도가", "수익률", "매도 이유"], rows, right=(3, 4, 5)))


def vi_table(vi, ds):
    x = vi[vi.date.isin(ds)] if len(vi) else vi
    if not len(x):
        return '<p class="empty">VI 복기 기록 없음</p>'
    rows = []
    for r in x.to_dict("records"):
        rows.append(("muted" if r["구분"] != "정식" else "", [f"<b>{E(r['종목명'])}</b>", fmt_d(r["date"], False), E(str(r["VI시각"])[:5]), E(r["구분"]),
                                                          E(r["결과"]), num(r.get("수익률(%)")), num(r.get("VI후최고(%)"), 1), num(r.get("VI후최저(%)"), 1), num(r.get("종가(%)"), 1)]))
    o = x[x["구분"] == "정식"]
    n, w, a = stat(o["수익률(%)"]) if len(o) else (0, None, None)
    head = f'<p class="kpi">정식 시간 {len(o)}건 중 매매 {n}건' + (f" · 승률 {w:.0f}% · 평균 {num(a)}" if n else "") + ' <small>흐린 줄은 시간 밖(참고)</small></p>'
    return head + wide(["종목", "날짜", "VI 시각", "구분", "결과", "수익률", "VI 뒤 최고", "VI 뒤 최저", "종가"], rows, right=(5, 6, 7, 8))


def msg_html(m):
    body = m["text"] if m.get("html") else E(m["text"])
    body = body.replace("\n<pre>", "<pre>").replace("</pre>\n", "</pre>").replace("\n\n", "\n")
    tag = '<span class="src vi">노트북 VI봇</span>' if m["src"] == "VI" else ""
    return f'<article class="msg"><time>{E(m["t"])}</time><div class="bubble">{tag}{body}</div></article>'


def trades_wide(t):
    if not len(t):
        return '<p class="empty">끝난 매매 없음</p>'
    t = t.assign(_s=t.매매법.map(lambda s: STAGE_ORDER.index(STAGE.get(s, "중기 스윙")))).sort_values(["_s", "매매법"])
    rows = [[f"<b>{E(r['종목'])}</b>", E(STAGE.get(r["매매법"], "")), E(SHOW_NAME.get(r["매매법"], r["매매법"])), E(r["구분"]), E(r["산 날"]), E(r["판 날"]),
             num(r["수익률(%)"]), E(r["메모"])] for r in t.to_dict("records")]
    return wide(["종목", "단계", "매매법", "구분", "산 날", "판 날", "수익률", "메모"], rows, right=(6,))


# ---------- 달력 ----------
def month_cal(ym, days_set, cell, href, week_link=True):
    y, m = int(ym[:4]), int(ym[4:])
    head = ('<div class="cal-h">주</div>' if week_link else "") + "".join(f'<div class="cal-h">{w}</div>' for w in "월화수목금")
    body = ""
    for wk in calendar.Calendar(0).monthdatescalendar(y, m):
        mon = wk[0].strftime("%Y%m%d")
        if week_link:
            has = any(x.strftime("%Y%m%d") in days_set for x in wk[:5])
            body += (f'<a class="cal-w" href="{href("w:" + mon)}">{wk[0].month}/{wk[0].day}<br>주간</a>' if has else '<div class="cal-w off"></div>')
        for x in wk[:5]:
            d = x.strftime("%Y%m%d")
            if x.month != m:
                body += '<div class="cal-d off"></div>'
            elif d in days_set:
                body += f'<a class="cal-d" href="{href(d)}"><b>{x.day}</b>{cell(d)}</a>'
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
        n, w, a = stat(td["수익률(%)"])
        s += f'<span class="dot">매매 {n}건</span>{num(a, 1)}'
    return s


def market_cell(d, lead):
    mk = market(d)
    s = ""
    if mk:
        s += f'<span>코 {num(mk.get("kospi"), 1)}</span><span>닥 {num(mk.get("kosdaq"), 1)}</span>'
        th = (mk.get("hot") or [{}])[0].get("name") or (mk.get("themes") or [{}])[0].get("name")
        if th:
            s += chip(th)
    elif len(lead) and (lead.date == d).any():
        s += f'<span class="dot">{E(lead[lead.date == d].name.iloc[0])}</span>'
    return s


# ---------- 페이지 ----------
CSS = """
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
.cal-d .chip{font-size:11px;padding:0 4px;overflow:hidden;text-overflow:ellipsis;max-width:100%}
.dot{font-size:11.5px;color:var(--mute)}
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
<footer>평일 15:10·19:00 알림 뒤 자동으로 새로 만들어집니다. 수익률은 비용 0.35%를 뺀 값이고, 모의 기록은 실제 매매가 아닙니다.</footer></main></body></html>"""


def index_page(days, t, h, fm, vi, expect):
    k = []
    if days and market(days[0]):
        mk = market(days[0])
        k.append((f'{num(mk.get("kospi"))} <small>/</small> {num(mk.get("kosdaq"))}', f"코스피 / 코스닥 ({fmt_d(days[0], False)})"))
    if len(fm):
        n, w, a = stat(fm.ret); k.append((num(a), f"15분봉 MACD·일목 단타 모의 ({n}건, 승률 {w:.0f}%)"))
    vv = t[(t.매매법 == "VI 단타") & t.구분.str.contains("정식")] if len(t) else t
    if len(vv):
        n, w, a = stat(vv["수익률(%)"]); k.append((num(a), f"VI 단타 자동 복기 ({n}건)"))
    cb = t[(t.매매법 == "종가베팅") & (t.구분 != "쉰 날 후보(참고)")] if len(t) else t
    if len(cb):
        n, w, a = stat(cb["수익률(%)"]); k.append((num(a), f"종가베팅 ({n}건)"))
    body = ('<div class="kpis">' + "".join(f"<div><b>{a}</b><span>{b}</span></div>" for a, b in k) + "</div>") if k else ""
    body += '<h2>매매법별 누적 성적</h2><p class="sub">보유 기간으로 4단계로 나눴어요. 표는 옆으로 밀어서 보세요.</p>' + strat_rows(t, expect)
    body += "<h2>지금 진행 중</h2>" + holdings(h)
    ds = set(days)
    body += '<h2 id="cal">알림 달력</h2><p class="sub">날짜를 누르면 그날 알림이, 왼쪽 "주간"을 누르면 그 주 복기가 열려요.</p>'
    body += "".join(month_cal(ym, ds, lambda d: alert_cell(d, t), lambda d: f"w/{d[2:]}.html" if d.startswith("w:") else f"d/{d}.html") for ym in months(days))
    if days:
        ms = messages(days[0])
        body += f'<h2>최근 알림 · {fmt_d(days[0])}</h2>'
        body += "".join(msg_html(m) for m in ms[-4:]) if ms else '<p class="empty">저장된 알림 원문 없음</p>'
        body += f'<p><a href="d/{days[0]}.html">이날 전체 보기 →</a></p>'
    now = dt.datetime.now(dt.timezone(dt.timedelta(hours=9))).strftime("%m/%d %H:%M")
    return page("오늘의 알림장", f"마지막 갱신 {now}", body, "처음")


def day_page(d, t, fm, lead, vi):
    ms = messages(d)
    td = t[t["판 날"].astype(str).str.replace("-", "") == d] if len(t) else t
    body = f'<nav class="tabs"><a href="../m/{d}.html">이날 시장·대장주</a><a href="../w/{monday(d)}.html">이번 주 복기</a></nav>'
    body += "<h2>보낸 알림</h2>" + ("".join(msg_html(m) for m in ms) if ms else '<p class="empty">이날 저장된 알림 원문 없음 (봇은 11/20부터, 노트북 VI봇은 다시 켠 뒤부터 저장)</p>')
    body += "<h2>대장주</h2>" + leaders_table(lead, d, market(d))
    body += "<h2>초단타 · VI 단타 자동 복기</h2>" + vi_table(vi, [d])
    body += f"<h2>초단타 · {M15} 모의</h2>" + m15_table(fm, [d])
    body += "<h2>이날 끝난 매매 (전체)</h2>" + trades_wide(td)
    return page(fmt_d(d) + " 알림", f"알림 {len(ms)}개", body, depth=1)


def market_page_day(d, lead):
    mk = market(d) or {}
    body = f'<nav class="tabs"><a href="../d/{d}.html">이날 알림</a><a href="../w/{monday(d)}.html">이번 주 복기</a></nav>'
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
        body += '<p class="empty">이날 지수·테마 기록 없음 (11/20부터 저장)</p>'
    body += '<h2>대장주</h2><p class="sub">+10% 이상·거래대금 100억 이상, 거래대금 순. 이름 앞 색 막대가 테마 색이에요.</p>' + leaders_table(lead, d, mk)
    return page(fmt_d(d) + " 시장", "코스피·코스닥, 테마, 대장주", body, depth=1)


def market_page(days, lead):
    body = '<p class="sub">날짜마다 코스피(코)·코스닥(닥) 등락과 그날 돈이 가장 몰린 테마예요. 누르면 테마별 상승률과 대장주가 나와요.</p>'
    body += "".join(month_cal(ym, set(days), lambda d: market_cell(d, lead), lambda d: f"m/{d}.html", week_link=False) for ym in months(days))
    seen = []
    for d in days[:20]:
        for x in (market(d) or {}).get("hot", []):
            if x["name"] not in seen:
                seen.append(x["name"])
    if seen:
        body += "<h3>최근 자주 나온 테마</h3><p>" + " ".join(chip(s, False) for s in seen[:20]) + "</p>"
    return page("대장주 달력", "시장 흐름을 날짜별로", body, "대장주 달력")


def week_page(mon, days, t, fm, lead, vi, expect):
    end = (dt.datetime.strptime(mon, "%Y%m%d") + dt.timedelta(days=4)).strftime("%Y%m%d")
    wk = [d for d in days if mon <= d <= end]
    tw = t[(t["판 날"].astype(str).str.replace("-", "") >= mon) & (t["판 날"].astype(str).str.replace("-", "") <= end)] if len(t) else t
    body = '<div class="cal cal5">' + "".join(f'<div class="cal-h">{w}</div>' for w in "월화수목금")
    for i in range(5):
        d = (dt.datetime.strptime(mon, "%Y%m%d") + dt.timedelta(days=i)).strftime("%Y%m%d")
        body += (f'<a class="cal-d" href="../d/{d}.html"><b>{int(d[6:])}</b>{market_cell(d, lead)}{alert_cell(d, t)}</a>' if d in wk else f'<div class="cal-d none"><b>{int(d[6:])}</b></div>')
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
            rows.append([f'<span class="bar" style="--c:{color(th)}"></span><b>{E(r.name)}</b>', fmt_d(r.date, False), chip(th), num(r.ret, 1),
                         num(getattr(r, "next_open", None), 1), num(getattr(r, "next_close", None), 1), E(r.reason)])
        body += wide(["종목", "날짜", "테마", "그날", "다음날 시가", "다음날 종가", "오른 이유 후보"], rows, right=(3, 4, 5))
    else:
        body += '<p class="empty">기록 없음</p>'
    body += "<h2>초단타 · VI 단타 자동 복기</h2>" + vi_table(vi, wk)
    body += f"<h2>초단타 · {M15} 모의</h2>" + m15_table(fm, wk)
    body += "<h2>이번 주 끝난 매매 (전체)</h2>" + trades_wide(tw)
    x = dt.datetime.strptime(mon, "%Y%m%d")
    return page(f"{x.month}월 {x.day}일 주간 복기", f"{fmt_d(mon)} ~ {fmt_d(end)}", body, depth=1)


def main():
    t, h, fm, lead, vi, expect = load()
    days = all_dates(t, fm, lead, vi)
    for sub in ("d", "w", "m"):
        os.makedirs(os.path.join(OUT, sub), exist_ok=True)
    open(os.path.join(OUT, ".nojekyll"), "w").close()
    W = lambda p, txt: open(os.path.join(OUT, p), "w", encoding="utf-8").write(txt)
    for d in days:
        W(f"d/{d}.html", day_page(d, t, fm, lead, vi))
        W(f"m/{d}.html", market_page_day(d, lead))
    for m in sorted({monday(d) for d in days}):
        W(f"w/{m}.html", week_page(m, days, t, fm, lead, vi, expect))
    W("index.html", index_page(days, t, h, fm, vi, expect))
    W("market.html", market_page(days, lead))
    print(f"페이지 만듦: 날짜 {len(days)}일, 주 {len({monday(d) for d in days})}개 → {OUT}")


if __name__ == "__main__":
    main()
