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

  async function acct(el) {
    const btn = `<p class="syncrow"><a class="syncbtn" href="https://t.me/${BOT}?start=sync" target="_blank" rel="noopener">📲 현재 동기화</a>
      <small id="syncmsg">누르면 텔레그램 종가베팅 봇이 열려요. '동기화'가 보내지면 데스크톱 봇이 1~2분 안에 계좌·지표를 올려요.</small></p>`;
    let last = "";
    const draw = async () => {
      try { const j = await get("live/now.json"); el.innerHTML = btn + acctHtml(j); const changed = last && last !== j.updated; last = j.updated; return changed; }
      catch (e) { el.innerHTML = btn + `<p class="empty">아직 데스크톱 봇이 올린 계좌 정보가 없어요.</p>`; return false; }
    };
    await draw();
    el.addEventListener("click", e => {
      if (!e.target.closest(".syncbtn")) return;
      let n = 0; const msg = () => document.getElementById("syncmsg");
      const tick = setInterval(async () => {
        n++; if (msg()) msg().textContent = `동기화 기다리는 중… (${n * 20}초)`;
        if (await draw() || n >= 12) { clearInterval(tick); if (msg()) msg().textContent = n >= 12 ? "3분 동안 새 정보가 없어요. 데스크톱이 켜져 있는지 확인해 주세요." : "✅ 방금 갱신됐어요."; }
      }, 20000);
    });
  }

  /* ---------- 장중 흐름 ---------- */
  function flowHtml(j) {
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
      el.innerHTML = (el.dataset.d ? "" : `<p class="sub">${day.slice(0, 4)}.${day.slice(4, 6)}.${day.slice(6)} · <a href="d/${day}.html">이날 알림 전체</a></p>`) + flowHtml(j);
    } catch (e) { el.innerHTML = `<p class="empty">이날 장중 흐름 기록 없음 (데스크톱 봇 30분 알림부터 저장)</p>`; }
  }

  document.querySelectorAll("#acct").forEach(acct);
  document.querySelectorAll(".flow").forEach(flow);
})();
