/* 알림장 실시간 칸: 데스크톱 모의주문봇이 올린 docs/live/*.json 을 읽어 그림
   - #acct : 모의 계좌 + 지금 지표 + '현재 동기화' 버튼   (live/now.json)
   - #flow : 그날 30분마다 장중 흐름                       (live/날짜.json)
   페이지를 다시 만들지 않아도 파일만 바뀌면 바로 보임 */
(() => {
  const BOT = "jh_closing_bet_bot";
  const base = document.currentScript.src.replace(/live\.js.*$/, "");
  const E = s => String(s ?? "").replace(/[&<>"]/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
  const won = v => v == null ? "–" : Math.round(v).toLocaleString("ko-KR");
  const man = v => v == null ? "–" : (Math.abs(v) >= 1e8 ? (v / 1e8).toFixed(2) + "억" : Math.round(v / 1e4).toLocaleString("ko-KR") + "만");
  const pct = (v, nd = 2) => v == null || isNaN(v) ? "–" : `<span class="${v > 0 ? "up" : v < 0 ? "dn" : ""}">${v > 0 ? "+" : ""}${(+v).toFixed(nd)}%</span>`;
  const chip = t => t && t.name ? `<span class="chip" style="--c:${t.c || "#8a959c"}" title="${E(t.name)}">${E(t.name.split("(")[0].trim())}</span>` : "";
  const get = async p => { const r = await fetch(base + p + "?t=" + Date.now(), { cache: "no-store" }); if (!r.ok) throw r.status; return r.json(); };
  const stock = (n, r) => n ? `<b>${E(n)}</b> ${pct(r, 1)}` : "–";

  /* ---------- 모의 계좌 ---------- */
  function acctHtml(j) {
    const a = j.account || {}, m = j.market || {}, hs = a.holdings || [];
    let h = `<p class="kpi"><span class="badge test">모의</span> 마지막 동기화 <b>${E(j.updated)}</b> <small>(${E(j.reason || "")})</small></p>`;
    h += `<div class="kpis"><div><b>${man(a.total)}</b><span>총자산 (현금 + 주식)</span></div>
      <div><b>${pct(a.ret_total)}</b><span>시작 ${man(a.start)} 대비</span></div>
      <div><b>${pct(a.ret_eval)}</b><span>보유 주식 평가 수익률<br>${a.pnl_eval >= 0 ? "+" : ""}${won(a.pnl_eval)}원</span></div>
      <div><b>${man(a.cash)}</b><span>현금 (주문 가능)</span></div></div>`;
    if (hs.length) {
      const rows = hs.map(x => `<tr><td><b>${E(x.name)}</b><small class="k"> ${E(x.strategy || "")}</small></td>
        <td class="r">${pct(x.ret)}</td><td class="r">${won(x.qty)}주</td>
        <td class="r">${won(x.avg)} → <b>${won(x.price)}</b></td><td class="r">${won(x.value)}</td><td class="r">${a.total ? (x.value / a.total * 100).toFixed(1) + "%" : "–"}</td></tr>`).join("");
      h += `<div class="scroll"><table class="wide"><thead><tr><th>종목 · 전략</th><th class="r">수익률</th><th class="r">수량</th><th class="r">평단 → 현재가</th><th class="r">평가금액</th><th class="r">비중</th></tr></thead><tbody>${rows}</tbody></table></div>`;
    } else h += `<p class="empty">보유 종목 없음</p>`;
    const ix = ["kospi", "kosdaq"].filter(k => m[k]).map(k => {
      const x = m[k]; return `<div><b>${pct(x.chg)}</b><span>${k === "kospi" ? "코스피" : "코스닥"} ${x.price ? (+x.price).toFixed(2) : ""}<br>20일선 ${pct(x.ma20_gap, 1)}</span></div>`;
    }).join("");
    if (ix) h += `<h3>지금 지표 <small>${E(m.time || "")}</small></h3><div class="kpis">${ix}</div>`;
    if ((m.themes || []).length)
      h += `<div class="scroll"><table class="wide"><thead><tr><th>지금 테마</th><th class="r">3%↑</th><th>대장</th><th>2등</th></tr></thead><tbody>` +
        m.themes.slice(0, 5).map((t, i) => `<tr><td>${i + 1}. ${chip(t)}</td><td class="r">${t.n ?? ""}</td><td>${stock(t.lead, t.lead_ret)}</td><td>${stock(t.second, t.second_ret)}</td></tr>`).join("") + `</tbody></table></div>`;
    return h;
  }

  /* ---------- 실계좌 (수익률·비중만) ---------- */
  function realHtml(j) {
    const r = j.real;
    if (!r) return `<p class="empty">실계좌 동기화 정보 없음 (데스크톱에 실계좌 키를 넣으면 보여요)</p>`;
    let h = `<p class="kpi"><span class="badge real">실제</span> 키움 · 마지막 동기화 <b>${E(j.updated)}</b> · ${r.n}종목 · 보유 평가 ${pct(r.ret_eval)}</p>`;
    if ((r.holdings || []).length)
      h += `<div class="scroll"><table class="wide"><thead><tr><th>종목</th><th class="r">수익률</th><th class="r">비중</th><th class="r">평단 → 현재가</th></tr></thead><tbody>` +
        r.holdings.map(x => `<tr><td><b>${E(x.name)}</b><small class="k"> ${E(x.account || "")}</small></td><td class="r">${pct(x.ret)}</td>
          <td class="r">${x.weight == null ? "–" : (+x.weight).toFixed(1) + "%"}</td><td class="r">${won(x.avg)} → <b>${won(x.price)}</b></td></tr>`).join("") + `</tbody></table></div>`;
    else h += `<p class="empty">키움 실계좌 보유 종목 없음</p>`;
    return h + `<p class="sub">수량·금액은 올리지 않아요 (페이지가 공개라서). 수익률은 키움 기준(수수료·세금 반영).</p>`;
  }

  async function acct(el) {
    const btn = `<p class="syncrow"><a class="syncbtn" href="https://t.me/${BOT}?start=sync" target="_blank" rel="noopener">📲 현재 동기화</a>
      <small id="syncmsg">누르면 텔레그램 종가베팅 봇이 열려요. '동기화'가 보내지면 데스크톱 봇이 1~2분 안에 계좌·지표를 올려요.</small></p>`;
    let last = "";
    const draw = async () => {
      try { const j = await get("live/now.json"); if (el) el.innerHTML = btn + acctHtml(j);
        const rn = document.getElementById("realnow"); if (rn) rn.innerHTML = btn.replace('id="syncmsg"', 'class="syncmsg2"') + realHtml(j); const changed = last && last !== j.updated; last = j.updated; return changed; }
      catch (e) { if (el) el.innerHTML = btn + `<p class="empty">아직 데스크톱 봇이 올린 계좌 정보가 없어요.</p>`; const rn = document.getElementById("realnow"); if (rn) rn.innerHTML = `<p class="empty">아직 동기화된 정보가 없어요.</p>`; return false; }
    };
    await draw();
    document.addEventListener("click", e => {
      if (!e.target.closest(".syncbtn")) return;
      let n = 0; const msg = () => document.getElementById("syncmsg");
      const tick = setInterval(async () => {
        n++; if (msg()) msg().textContent = `동기화 기다리는 중… (${n * 20}초)`;
        if (await draw() || n >= 12) { clearInterval(tick); if (msg()) msg().textContent = n >= 12 ? "3분 동안 새 정보가 없어요. 데스크톱이 켜져 있는지 확인해 주세요." : "✅ 방금 갱신됐어요."; }
      }, 20000);
    });
  }

  /* ---------- 장중 흐름 ---------- */
  function flowHtml(j, compact) {
    const S = (j.snaps || []).filter(s => (s.themes || []).length || (s.upper || []).length);
    if (!S.length) return `<p class="empty">이날 장중 흐름 기록 없음</p>`;
    // 1) 1위 테마가 바뀐 순간만 이어서
    let chain = [], prev = null;
    S.forEach(s => { const t = (s.themes || [])[0]; if (t && t.name !== prev) { chain.push(`<span class="nowrap"><time>${E(s.t)}</time> ${chip(t)}</span>`); prev = t.name; } });
    let h = `<p class="kpi"><b>1위 테마 흐름</b> ${chain.join(" → ") || "–"}</p>`;
    // 2) 테마 순위표: 줄=테마, 칸=시각
    const info = {};
    S.forEach((s, i) => (s.themes || []).slice(0, 5).forEach((t, r) => { (info[t.name] ||= { t, rank: {}, sum: 0, n: 0 }); info[t.name].rank[i] = r + 1; info[t.name].sum += 6 - (r + 1); info[t.name].n++; info[t.name].t = t; }));
    const order = Object.values(info).sort((a, b) => b.sum - a.sum);
    const th = S.map(s => `<th class="r">${E(s.t)}</th>`).join("");
    const rows = order.map(o => `<tr><td>${chip(o.t)} <small>${o.n}번</small></td>` + S.map((_, i) => {
      const r = o.rank[i]; return `<td class="r rk${r || 0}">${r || "·"}</td>`;
    }).join("") + `</tr>`).join("");
    h += `<h3>테마 순위표 <small>숫자 = 그 시각 순위 (1~5위)</small></h3><div class="scroll"><table class="wide rank"><thead><tr><th>테마</th>${th}</tr></thead><tbody>${rows}</tbody></table></div>`;
    if (compact) {
      const up = new Set(); S.forEach(s => (s.upper || []).forEach(u => up.add(u.name)));
      return h + (up.size ? `<p class="kpi"><b>상한가</b> ${[...up].map(E).join(", ")}</p>` : "");
    }
    // 3) 상한가 누적
    const seen = new Set(), up = [];
    S.forEach(s => { const nw = (s.upper || []).filter(u => !seen.has(u.name)); nw.forEach(u => seen.add(u.name)); if (nw.length) up.push(`<li><time>${E(s.t)}</time> ${nw.map(u => `<b>${E(u.name)}</b> ${chip(u.theme ? { name: u.theme, c: u.c } : null)}`).join(" · ")}</li>`); });
    h += `<h3>상한가 <small>처음 잡힌 시각 · 모두 ${seen.size}종목</small></h3>` + (up.length ? `<ul class="tl">${up.join("")}</ul>` : `<p class="empty">상한가 없음</p>`);
    // 4) 시각별 카드 (최근 것이 위, 맨 위만 펼침)
    h += `<h3>시각별 자세히</h3>`;
    S.slice().reverse().forEach((s, k) => {
      const i = S.length - 1 - k, p = S[i - 1];
      const pr = {}; (p?.themes || []).slice(0, 5).forEach((t, r) => pr[t.name] = r + 1);
      const mv = (name, r) => { if (!p) return ""; const o = pr[name]; if (!o) return `<span class="new">새로</span>`; return o > r ? `<span class="up">▲${o - r}</span>` : o < r ? `<span class="dn">▼${r - o}</span>` : `<small>–</small>`; };
      const top = (s.themes || []).slice(0, 5).map((t, r) => `<tr><td>${r + 1}. ${chip(t)} ${mv(t.name, r + 1)}</td><td class="r">${t.n ?? ""}</td><td>👑 ${stock(t.lead, t.lead_ret)}</td><td>② ${stock(t.second, t.second_ret)}</td></tr>`).join("");
      let b = top ? `<div class="scroll"><table class="wide"><thead><tr><th>테마 순위</th><th class="r">3%↑</th><th>대장</th><th>2등</th></tr></thead><tbody>${top}</tbody></table></div>` : "";
      if ((s.upper || []).length) b += `<p><b>상한가</b> ${s.upper.map(u => E(u.name)).join(", ")}</p>`;
      if ((s.surge || []).length) b += `<p><b>돈 급증</b> <small>직전 알림 이후 거래대금이 크게 늘어난 종목</small><br>${s.surge.map(x => `${stock(x.name, x.ret)}${x.amt ? ` <small>+${man(x.amt)}</small>` : ""}`).join(" · ")}</p>`;
      if ((s.top_amt || []).length) b += `<p><b>거래대금 상위</b> ${s.top_amt.map(x => stock(x.name, x.ret)).join(" · ")}</p>`;
      const head = (s.themes || [])[0];
      h += `<details class="fold"${k === 0 ? " open" : ""}><summary><time>${E(s.t)}</time> 1위 ${chip(head) || "–"}${(s.upper || []).length ? ` · 상한가 ${s.upper.length}` : ""}</summary>${b}</details>`;
    });
    return h;
  }

  async function flow(el) {
    const d = el.dataset.d || new URLSearchParams(location.search).get("d");
    try {
      let day = d;
      if (!day) { const n = await get("live/now.json"); day = (n.date || "").replace(/-/g, ""); }
      const j = await get(`live/${day}.json`);
      el.innerHTML = (el.dataset.d ? "" : `<p class="sub">${day.slice(0, 4)}.${day.slice(4, 6)}.${day.slice(6)} · <a href="d/${day}.html">이날 기록 전체</a></p>`) + flowHtml(j, !!el.dataset.compact);
    } catch (e) { el.innerHTML = `<p class="empty">이날 장중 흐름 기록 없음 (데스크톱 봇 30분 알림부터 저장)</p>`; }
  }


  /* ---------- (11/28 개편) 홈·성적·보관 — 집 PC가 올린 records/summary.json 을 읽음 ---------- */
  const kst = () => new Date(Date.now() + 9 * 3600e3);
  const ymd = d => d.toISOString().slice(0, 10).replace(/-/g, "");
  const hm = d => d.toISOString().slice(11, 16);
  const tm = v => v ? String(v).slice(9, 14) : "";
  const st = x => x && x.n ? x : null;
  const fade = (x, txt) => `<span class="${x && x.n < 30 ? "thin" : ""}">${txt}</span>`;
  const find = (s, f) => (s.strategies || []).find(x => x.file === f) || {};
  const grp = (it, word) => { const g = it.groups || {}; const k = Object.keys(g).find(k => k.toUpperCase().includes(word)); return k ? g[k] : null; };

  function botRows(s) {
    const m = s.m1 || {}, hb = m.heartbeat || {}, cs = m.cs_stop || {};
    const now = kst(), today = ymd(now), t = hm(now), wk = now.getUTCDay() % 6 === 0;
    const slot = (label, a, b, start, end) => {
      const s0 = (hb[a] || "").startsWith(today), s1 = (hb[b] || "").startsWith(today);
      if (wk) return [label, "wait", "쉬는 날", ""];
      if (s0 && s1) return [label, "ok", "정상", `${tm(hb[a])} 시작 → ${tm(hb[b])} 끝`];
      if (s0 && t >= end) return [label, "no", "멈춤", `${tm(hb[a])}에 시작했는데 끝난 기록이 없어요`];
      if (s0) return [label, "wait", "도는 중", `${tm(hb[a])} 시작`];
      if (t >= start) return [label, "no", "빠짐", `${start}까지 실행 기록이 없어요 (휴장일이면 정상)`];
      return [label, "wait", "대기", ""];
    };
    const rows = [slot("<b>아침 08:40</b> 시가 매도·M1", "sell_start", "sell_end", "09:15", "09:20"),
                  slot("<b>오후 15:00</b> 계획·매수", "buy_start", "buy_end", "15:10", "15:45")];
    rows.splice(1, 0, ["<b>장중</b> CAN SLIM 손절 감시", cs.date === today ? "ok" : "wait", cs.date === today ? "정상" : "대기",
      cs.date === today ? `오늘 손절가 ${Object.keys(cs.stop || {}).length}종목` : ""]);
    let h = `<div class="st">` + rows.map(([l, c, w, d]) => `<div class="${c === "no" ? "bad" : ""}"><span>${l}${d ? `<small>${E(d)}</small>` : ""}</span><span class="${c}">${w}</span></div>`).join("") + `</div>`;
    const up = s.updated ? new Date(s.updated.replace(" ", "T") + ":00+09:00") : null;
    if (up && !wk && t >= "08:30" && t <= "20:00" && Date.now() - up > 3 * 3600e3)
      h += `<p class="kpi"><span class="no">집 PC 기록이 ${Math.round((Date.now() - up) / 3600e3)}시간째 안 올라와요</span> — PC가 켜져 있는지 확인</p>`;
    return h;
  }

  function homeHtml(s) {
    const m = s.m1 || {}, a = s.mock_account || {}, pk = m.peak, cs = (m.cs_stop || {}).stop || {}, mk = s.market || {};
    let h = `<p class="sub">집 PC 기록 ${E(s.updated || "–")} 기준</p><h2>1. 봇 상태</h2>` + botRows(s);
    // 2. 계좌 + 킬스위치
    const dd = pk && pk.peak && a.total ? (a.total / pk.peak - 1) * 100 : null;
    const lv = dd == null ? -1 : dd <= -25 ? 3 : dd <= -20 ? 2 : dd <= -15 ? 1 : 0;
    const lvt = ["안전", "-15% 경보", "-20% 매수멈춤", "-25% 정지"];
    h += `<h2>2. 내 계좌 <small>모의</small></h2><div class="kpis kn" style="grid-template-columns:repeat(2,minmax(0,1fr))"><div><b>${pct(a.ret_total)}</b><span>시작 대비 · ${man(a.total)}</span></div>
      <div><b>${dd == null ? "–" : pct(dd, 1)}</b><span>고점 대비 · ${dd == null ? "11/30부터 기록" : lvt[lv]}${pk && pk.halted ? " · 지금 멈춤" : ""}</span></div></div>
      <div class="ks"><i></i><i></i><i></i><i></i></div><div class="ksl">${lvt.map((x, i) => `<span class="${i === lv ? "on" : ""}">${x}</span>`).join("")}</div>`;
    if (s.real && (s.real.holdings || []).length)
      h += `<p class="kpi"><span class="badge real">실제</span> 보유 평가 ${pct(s.real.ret_eval)} · ${s.real.holdings.length}종목 <small>(금액은 안 올려요)</small></p>`;
    // 3. 칸별
    h += `<h2>3. 칸별 지금 상태</h2>`;
    const p1 = m.m1 || {};
    h += `<div class="card"><div class="hd"><b>M1 바닥 칸 <small>비중 50%</small></b><small>월 1회</small></div>` +
      (p1.code ? `<p>${E(p1.code)} ${won(p1.qty)}주 · 평단 ${won(p1.buy)} <small>${E(p1.since || "")}부터</small></p>`
               : `<p><small>${E(p1.note || "아직 매매 없음")}</small></p>`) + `</div>`;
    const hs = a.holdings || [], cl = hs.filter(x => cs[x.code] != null), etc = hs.filter(x => cs[x.code] == null);
    const tbl = (xs, stop) => `<table class="wide"><thead><tr><th>종목</th><th class="r">수익률</th>${stop ? '<th class="r">손절가</th>' : ""}</tr></thead><tbody>` +
      xs.map(x => `<tr><td>${E(x.name)}</td><td class="r">${pct(x.ret, 1)}</td>${stop ? `<td class="r">${won(cs[x.code])}</td>` : ""}</tr>`).join("") + `</tbody></table>`;
    h += `<div class="card"><div class="hd"><b>CAN SLIM <small>종목당 5% · 최대 5</small></b><small>${cl.length}종목</small></div>` +
      (cl.length ? tbl(cl, 1) : `<p><small>손절 감시 중인 종목 없음</small></p>`) + `</div>`;
    if (etc.length) h += `<div class="card"><div class="hd"><b>그 밖의 모의 보유</b><small>${etc.length}종목</small></div>${tbl(etc, 0)}</div>`;
    h += `<div class="card"><div class="hd"><b>종가베팅 <small>비중 10%</small></b></div><p>신규 매수 <b class="${mk.state === "켜짐" ? "up" : "dn"}">${mk.state === "켜짐" ? "가능" : mk.state ? "쉼" : "–"}</b>
      <small>코스피 20일선 ${pct(mk.kospi_ma20_gap, 1)} · 코스닥 ${pct(mk.kosdaq_ma20_gap, 1)}</small></p></div>`;
    return h + `<p class="sub" style="margin-top:20px">아래 '오늘 할 일'이 오늘 온 알림이에요.</p>`;
  }

  function scoreHtml(s) {
    const zj = find(s, "종가베팅_모의.csv"), mid = find(s, "중기_모의.csv"), m1 = find(s, "M1_모의.csv");
    const cs = grp(mid, "CAN");
    const k = (x, label) => `<div><b>${x && x.n ? fade(x, pct(x.avg)) : "–"}</b><span>${label}<br>${x && x.n ? `끝난 ${x.n}건 · 승률 ${x.win}%` : "아직 끝난 매매 없음"}</span></div>`;
    let h = `<h2>1. 칸별 성적 <small>모의 · 1건 평균</small></h2><div class="kpis kn" style="grid-template-columns:repeat(3,minmax(0,1fr))">${k(m1.total, "M1 바닥 칸")}${k(cs, "CAN SLIM")}${k(zj.total, "종가베팅")}</div>`;
    const rm = s.report_mock || {}, names = Object.keys(rm).filter(x => x !== "summary");
    h += `<h2>2. 리포트 모의 ①②③ <small>가상 1억 · 주문 없음</small></h2>`;
    h += names.length ? `<table class="wide"><thead><tr><th>칸</th><th class="r">청산</th><th class="r">평균</th></tr></thead><tbody>` +
        names.map(n => `<tr><td>${E(n)}</td><td class="r">${rm[n].n || 0}건</td><td class="r">${rm[n].n ? fade(rm[n], pct(rm[n].avg)) : "–"}</td></tr>`).join("") + `</tbody></table>`
      : `<p class="empty">시작 전 — 12/1부터 평일 19:10 자동 계산</p>`;
    if ((rm.summary || []).length) h += `<details class="fold"><summary>요약 펼치기</summary>${rm.summary.map(x => `<p>${E(x)}</p>`).join("")}</details>`;
    // 3. 12/11 점검표
    const lg = (s.m1 || {}).hb_log || {}, days = Object.keys(lg).filter(d => d >= "20261130" && d <= "20261211").sort();
    const miss = days.filter(d => !["sell_start", "sell_end", "buy_start", "buy_end"].every(x => lg[d][x]));
    h += `<h2>3. 12/11 모의 점검표 <small>11/30 ~ 12/11</small></h2><div class="kpis kn" style="grid-template-columns:repeat(2,minmax(0,1fr))"><div><b>${miss.length}일</b><span>실행이 빠진 날 (기록된 ${days.length}일 중)<br>목표 0일</span></div>
      <div><b>–</b><span>체결 오차<br>12/11에 기록 파일로 계산</span></div></div>`;
    if (miss.length) h += `<p class="kpi">빠진 날: ${miss.map(d => `${+d.slice(4, 6)}/${+d.slice(6)}`).join(", ")}</p>`;
    h += `<ul class="chk"><li>□ M1 12/1 시가 매수 체결</li><li>□ CAN SLIM 장중 손절 1번 이상 작동</li><li>□ 킬스위치 고점 기록 매일 갱신</li><li>□ 빠짐 경보가 텔레그램으로 옴</li></ul>
      <p class="kpi">다 통과하면 → <b>12/14 소액 실전</b> 결정</p>`;
    return h;
  }

  function archiveHtml(s) {
    const rows = [["VI 단타", find(s, "VI단타_모의.csv").total], ["CM존 (주도주 첫 눌림)", find(s, "CM존_모의.csv").total],
      ["저가매수", grp(find(s, "중기_모의.csv"), "저가")], ["실험칸 (VI 다음날 등)", find(s, "실험칸_모의.csv").total],
      ["VI 알림봇 복기 (실계좌 알림)", find(s, "VI알림봇_복기.csv").total], ["VI 알림봇 신호대로 샀다면", find(s, "VI알림봇_신호매매.csv").total]];
    return `<h2>1. 멈춘 전략 <small>모의 멈춤 · 기록만 보관</small></h2><table class="wide"><thead><tr><th>전략</th><th class="r">끝난 건</th><th class="r">평균</th></tr></thead><tbody>` +
      rows.map(([n, x]) => `<tr><td>${n}</td><td class="r">${x && x.n ? x.n : 0}</td><td class="r">${x && x.n ? fade(x, pct(x.avg)) : "–"}</td></tr>`).join("") + `</tbody></table>`;
  }

  const sumPages = [["home", homeHtml], ["score", scoreHtml], ["archive", archiveHtml]].filter(([id]) => document.getElementById(id));
  if (sumPages.length) get("records/summary.json").then(s => sumPages.forEach(([id, f]) => {
    try { document.getElementById(id).innerHTML = f(s); } catch (e) { document.getElementById(id).innerHTML = `<p class="empty">그리지 못했어요 (${E(e)})</p>`; }
  })).catch(() => sumPages.forEach(([id]) => document.getElementById(id).innerHTML = `<p class="empty">집 PC 기록(summary.json)을 불러오지 못했어요.</p>`));

  if (document.getElementById("acct") || document.getElementById("realnow")) acct(document.getElementById("acct"));
  document.querySelectorAll(".flow").forEach(flow);
})();
