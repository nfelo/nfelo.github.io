(function () {
  "use strict";

  const content = document.getElementById("content");
  const nav = document.getElementById("site-nav");
  const menuButton = document.querySelector(".menu-button");
  const dataCache = new Map();
  const confidenceZ = 1.6448536269514715;
  let summary;
  let catalog;

  const escapeHTML = (value) => String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");

  const number = (value, digits = 0) => Number(value).toLocaleString("en", {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  });
  const rating = (value) => value == null ? "—" : number(value, 0);
  const percent = (value) => `${number(value * 100, 1)}%`;
  const validDate = (value) => {
    const [year, month, day] = String(value).split("-");
    if (month === "00") return year;
    if (day === "00") return `${year}-${month}`;
    const parsed = new Date(`${value}T00:00:00Z`);
    return Number.isNaN(parsed.valueOf())
      ? value
      : parsed.toLocaleDateString("en", { year: "numeric", month: "short", day: "numeric", timeZone: "UTC" });
  };
  const teamURL = (code) => `#/team/${encodeURIComponent(code)}`;
  const teamLink = (code, name) => `<a class="team-link" href="${teamURL(code)}">${escapeHTML(name)}</a>`;

  async function getJSON(path) {
    if (!dataCache.has(path)) {
      dataCache.set(path, fetch(new URL(path, document.baseURI), { cache: "no-cache" }).then((response) => {
        if (!response.ok) throw new Error(`Could not load ${path} (${response.status})`);
        return response.json();
      }));
    }
    return dataCache.get(path);
  }

  function setTitle(title) {
    document.title = title ? `${title} · Network Football Elo` : "Network Football Elo";
  }

  function parseRoute() {
    const raw = location.hash.startsWith("#/") ? location.hash.slice(2) : "";
    const [path, query = ""] = raw.split("?");
    const parts = path.split("/").filter(Boolean).map(decodeURIComponent);
    return { section: parts[0] || "home", value: parts[1] || "", query: new URLSearchParams(query) };
  }

  function setActiveNav(section) {
    nav.querySelectorAll("a").forEach((link) => {
      const target = link.getAttribute("href").replace("#/", "");
      if (target === section) link.setAttribute("aria-current", "page");
      else link.removeAttribute("aria-current");
    });
    nav.classList.remove("is-open");
    menuButton.setAttribute("aria-expanded", "false");
  }

  function loading(label = "Loading rating history…") {
    content.innerHTML = `<div class="loading-shell" role="status"><span class="spinner" aria-hidden="true"></span><p>${escapeHTML(label)}</p></div>`;
  }

  function formHTML(values) {
    return `<span class="form" aria-label="Recent form ${values.join(", ")}">${values.map((item) => `<i class="${item}">${item}</i>`).join("")}</span>`;
  }

  function probabilityHTML(values) {
    const labels = ["W", "D", "L"];
    const classes = ["pw", "pd", "pl"];
    return `<div class="probability" aria-label="Win ${percent(values[0])}, draw ${percent(values[1])}, loss ${percent(values[2])}">${values.map((value, index) => `<span class="${classes[index]}" style="width:${Math.max(12, value * 100)}%" title="${labels[index]} ${percent(value)}">${number(value * 100, 0)}</span>`).join("")}</div>`;
  }

  function renderHome() {
    setTitle("");
    const leaders = summary.current.slice(0, 3);
    const modelGain = (summary.validation.published_wfe_log_loss - summary.validation.log_loss) / summary.validation.published_wfe_log_loss * 100;
    const topTen = summary.current.slice(0, 10);
    const low = Math.min(...topTen.map((item) => item.rating)) - 10;
    const high = Math.max(...topTen.map((item) => item.rating));
    content.innerHTML = `
      <div class="page">
        <section class="hero">
          <p class="eyebrow">A predictive rating, rebuilt from 1872</p>
          <h1>Football strength through the <em>whole opponent network.</em></h1>
          <p class="lede">Every senior men's international in the source ledger, replayed with the best held-out model from the Great Elo Bake-off. Full covariance stops isolated match clusters pretending to be global certainty.</p>
          <div class="hero-actions">
            <a class="button button-primary" href="#/rankings">See the rankings</a>
            <a class="button" href="#/predict">Try a matchup</a>
          </div>
          <div class="hero-meta">
            <span><strong>${number(summary.meta.matches)}</strong>matches</span>
            <span><strong>${number(summary.meta.teams)}</strong>team histories</span>
            <span><strong>${validDate(summary.meta.results_through)}</strong>latest result</span>
          </div>
        </section>

        <section class="stat-grid" aria-label="Model summary">
          <article class="stat-card"><span class="label">Held-out log loss</span><strong class="value">${number(summary.validation.log_loss, 3)}</strong><span class="context">${number(modelGain, 2)}% below published WFE</span></article>
          <article class="stat-card"><span class="label">Full state</span><strong class="value">${number(summary.meta.teams)}²</strong><span class="context">opponent covariance matrix</span></article>
          <article class="stat-card"><span class="label">Update classes</span><strong class="value">1</strong><span class="context">common evidence weight</span></article>
          <article class="stat-card"><span class="label">Forecast classes</span><strong class="value">2</strong><span class="context">friendly vs competitive</span></article>
        </section>

        <section class="section">
          <div class="section-heading"><div><p class="eyebrow">Current order</p><h2>The leading three</h2></div><a class="button button-quiet" href="#/rankings">Full table →</a></div>
          <div class="leader-grid">${leaders.map((team, index) => `
            <article class="leader-card" data-rank="${index + 1}">
              <a href="${teamURL(team.code)}"><span class="rank">World no. ${index + 1}</span><h3>${escapeHTML(team.nation)}</h3><strong>${rating(team.rating)}</strong><p>network rating · ±${rating(team.se)} SE</p></a>
            </article>`).join("")}</div>
        </section>

        <section class="section split">
          <div>
            <div class="section-heading"><div><p class="eyebrow">Top ten</p><h2>Strength at a glance</h2></div></div>
            <div class="bar-chart" role="img" aria-label="Current top ten network ratings">${topTen.map((team) => `
              <div class="bar-row"><a href="${teamURL(team.code)}">${escapeHTML(team.nation)}</a><div class="bar-track"><div class="bar-fill" style="width:${Math.max(5, (team.rating - low) / Math.max(1, high - low) * 100)}%"></div></div><span class="bar-value">${rating(team.rating)}</span></div>`).join("")}</div>
          </div>
          <aside class="panel panel-dark">
            <p class="eyebrow">What changed</p>
            <h2>It is Elo-linked. It is not scalar Elo.</h2>
            <p class="muted">The prediction curve still uses the base-10 Elo logistic. The state is a dynamic Gaussian network: a result can update every connected team, uncertainty drifts between matches, and repeated games within an isolated cluster cannot manufacture global confidence.</p>
            <a class="button button-primary" href="#/methodology">Read the formulae</a>
          </aside>
        </section>

        <section class="section">
          <div class="section-heading"><div><p class="eyebrow">Record book</p><h2>Highest-rated matchups</h2></div><a class="button button-quiet" href="#/records">All records →</a></div>
          ${matchRecordTable(summary.top_matches.slice(0, 8))}
        </section>
      </div>`;
  }

  function rankingsTable(items, showRank) {
    if (!items.length) return `<div class="empty">No teams match those filters.</div>`;
    return `<div class="table-shell"><table>
      <thead><tr><th class="numeric">Rank</th><th>Team</th><th class="numeric">Network rating</th><th class="numeric hide-mobile">Posterior mean</th><th class="numeric hide-mobile">Matches</th><th>Recent form</th><th class="hide-mobile">All-time peak</th></tr></thead>
      <tbody>${items.map((team, index) => `<tr>
        <td class="rank-cell numeric">${showRank && team.rank ? team.rank : index + 1}</td>
        <td>${teamLink(team.code, team.nation)}</td>
        <td class="numeric"><span class="rating-main">${rating(team.rating)}</span><span class="rating-sub">SE ${rating(team.se)}</span></td>
        <td class="numeric hide-mobile">${rating(team.mean)}</td>
        <td class="numeric hide-mobile">${number(team.matches)}</td>
        <td>${formHTML(team.form || [])}</td>
        <td class="hide-mobile">${team.peak ? `${rating(team.peak.rating)} · ${validDate(team.peak.date)}` : "—"}</td>
      </tr>`).join("")}</tbody>
    </table></div>`;
  }

  function renderRankings() {
    setTitle("Rankings");
    content.innerHTML = `
      <div class="page">
        <header class="page-heading"><div><p class="eyebrow">Live network order</p><h1>Rankings</h1></div><p class="lede">The headline number is a one-sided 95% network rating: breadth-adjusted strength minus uncertainty. That is why a thin or disconnected schedule cannot sit above a well-identified elite team on raw mean alone.</p></header>
        <div class="toolbar">
          <div class="field field-grow"><label for="ranking-search">Find a team</label><input id="ranking-search" type="search" placeholder="Spain, Argentina, Japan…"></div>
          <div class="field"><label for="ranking-sort">Sort</label><select id="ranking-sort"><option value="rating">Rating</option><option value="mean">Posterior mean</option><option value="matches">Matches played</option><option value="name">Name</option></select></div>
          <div class="toggle-group" aria-label="Ranking pool"><button class="button button-dark" data-pool="current" aria-pressed="true">Current</button><button class="button" data-pool="all" aria-pressed="false">All histories</button></div>
        </div>
        <div class="record-note"><strong>NR</strong><div><b>Network rating</b> = breadth-adjusted posterior mean − 1.645 × standard error. Current eligibility requires 30 matches and activity within four years.</div></div>
        <div id="rankings-table"></div>
      </div>`;
    const target = document.getElementById("rankings-table");
    let pool = "current";
    const update = () => {
      const query = document.getElementById("ranking-search").value.trim().toLocaleLowerCase();
      const sort = document.getElementById("ranking-sort").value;
      const source = pool === "current" ? summary.current : summary.teams;
      const filtered = source.filter((team) => team.nation.toLocaleLowerCase().includes(query));
      filtered.sort((a, b) => sort === "name"
        ? a.nation.localeCompare(b.nation)
        : (b[sort] ?? -Infinity) - (a[sort] ?? -Infinity) || a.nation.localeCompare(b.nation));
      target.innerHTML = rankingsTable(filtered, pool === "current" && sort === "rating" && !query);
    };
    document.getElementById("ranking-search").addEventListener("input", update);
    document.getElementById("ranking-sort").addEventListener("change", update);
    document.querySelectorAll("[data-pool]").forEach((button) => button.addEventListener("click", () => {
      pool = button.dataset.pool;
      document.querySelectorAll("[data-pool]").forEach((peer) => {
        const selected = peer === button;
        peer.setAttribute("aria-pressed", String(selected));
        peer.classList.toggle("button-dark", selected);
      });
      update();
    }));
    update();
  }

  async function renderMatches(route) {
    setTitle("Matches");
    loading("Loading the historical match explorer…");
    const index = await getJSON("data/matches/index.json");
    const requestedTeam = route.query.get("team") || "";
    const latest = index.decades[index.decades.length - 1].decade;
    content.innerHTML = `
      <div class="page">
        <header class="page-heading"><div><p class="eyebrow">Every source result</p><h1>Matches</h1></div><p class="lede">Browse the complete chronological ledger. Every probability is genuinely pre-match; the rating columns are the conservative network values available at that moment.</p></header>
        <div class="toolbar">
          <div class="field"><label for="match-decade">Era</label><select id="match-decade"><option value="all">All ${number(summary.meta.matches)} matches</option>${index.decades.slice().reverse().map((item) => `<option value="${item.decade}" ${item.decade === latest ? "selected" : ""}>${item.decade}s · ${number(item.count)}</option>`).join("")}</select></div>
          <div class="field"><label for="match-team">Team</label><select id="match-team"><option value="">Any team</option>${summary.teams.map((team) => `<option value="${escapeHTML(team.code)}" ${team.code === requestedTeam ? "selected" : ""}>${escapeHTML(team.nation)}</option>`).join("")}</select></div>
          <div class="field"><label for="match-class">Class</label><select id="match-class"><option value="">All classes</option><option value="friendly">Friendly</option><option value="competitive">Competitive</option></select></div>
          <div class="field field-grow"><label for="match-search">Competition or opponent</label><input id="match-search" type="search" placeholder="World Cup, England, qualifier…"></div>
        </div>
        <p id="match-count" class="muted small"></p>
        <div id="match-table"></div>
        <div class="pagination"><button id="match-prev" class="button">← Newer</button><span id="match-page" class="muted small"></span><button id="match-next" class="button">Older →</button></div>
      </div>`;

    let rows = [];
    let page = 0;
    const pageSize = 100;
    const load = async () => {
      const decade = document.getElementById("match-decade").value;
      loadingTable();
      if (decade === "all") {
        const chunks = await Promise.all(index.decades.map((item) => getJSON(`data/matches/${item.file}`)));
        rows = chunks.flatMap((chunk) => chunk.matches).reverse();
      } else {
        rows = (await getJSON(`data/matches/${decade}.json`)).matches.slice().reverse();
      }
      page = 0;
      update();
    };
    const loadingTable = () => { document.getElementById("match-table").innerHTML = `<div class="loading-shell"><span class="spinner"></span><p>Loading matches…</p></div>`; };
    const filtered = () => {
      const team = document.getElementById("match-team").value;
      const cls = document.getElementById("match-class").value;
      const query = document.getElementById("match-search").value.trim().toLocaleLowerCase();
      return rows.filter((match) => {
        if (team && match.a !== team && match.b !== team) return false;
        if (cls === "friendly" && match.level !== 0) return false;
        if (cls === "competitive" && match.level === 0) return false;
        if (query && !`${match.an} ${match.bn} ${match.ac} ${match.bc} ${match.t}`.toLocaleLowerCase().includes(query)) return false;
        return true;
      });
    };
    const update = () => {
      const result = filtered();
      const pages = Math.max(1, Math.ceil(result.length / pageSize));
      page = Math.min(page, pages - 1);
      const visible = result.slice(page * pageSize, (page + 1) * pageSize);
      document.getElementById("match-count").textContent = `${number(result.length)} matches`;
      document.getElementById("match-page").textContent = `Page ${page + 1} of ${pages}`;
      document.getElementById("match-prev").disabled = page === 0;
      document.getElementById("match-next").disabled = page >= pages - 1;
      document.getElementById("match-table").innerHTML = matchTable(visible);
    };
    document.getElementById("match-decade").addEventListener("change", load);
    document.getElementById("match-team").addEventListener("change", () => { page = 0; update(); });
    document.getElementById("match-class").addEventListener("change", () => { page = 0; update(); });
    document.getElementById("match-search").addEventListener("input", () => { page = 0; update(); });
    document.getElementById("match-prev").addEventListener("click", () => { page -= 1; update(); scrollTo({ top: 0, behavior: "smooth" }); });
    document.getElementById("match-next").addEventListener("click", () => { page += 1; update(); scrollTo({ top: 0, behavior: "smooth" }); });
    await load();
  }

  function matchTable(matches) {
    if (!matches.length) return `<div class="empty">No matches found.</div>`;
    return `<div class="table-shell"><table><thead><tr><th>Date</th><th>Match</th><th class="numeric">Score</th><th class="hide-mobile">Competition</th><th>Pre-match W/D/L</th><th class="numeric hide-mobile">Combined NR</th></tr></thead><tbody>${matches.map((match) => `<tr>
      <td class="mono">${validDate(match.date)}</td>
      <td>${teamLink(match.a, match.an)} <span class="muted">v</span> ${teamLink(match.b, match.bn)}</td>
      <td class="numeric"><span class="score">${match.sa}–${match.sb}</span></td>
      <td class="hide-mobile">${escapeHTML(match.t)}</td>
      <td>${probabilityHTML(match.p)}</td>
      <td class="numeric hide-mobile">${rating(match.combined)}</td>
    </tr>`).join("")}</tbody></table></div>`;
  }

  function peakTable(peaks) {
    return `<div class="table-shell"><table><thead><tr><th class="numeric">Rank</th><th>Nation</th><th class="numeric">Peak NR</th><th>Date</th><th>Peak-making result</th><th class="hide-mobile">Competition</th></tr></thead><tbody>${peaks.map((peak, index) => `<tr>
      <td class="rank-cell numeric">${index + 1}</td><td>${teamLink(peak.code, peak.nation)}</td><td class="numeric"><span class="rating-main">${rating(peak.rating)}</span><span class="rating-sub">mean ${rating(peak.mean)} · SE ${rating(peak.se)}</span></td><td>${validDate(peak.date)}</td><td>${escapeHTML(peak.historical_name)} ${escapeHTML(peak.score)} ${escapeHTML(peak.opponent)}</td><td class="hide-mobile">${escapeHTML(peak.tournament)}</td>
    </tr>`).join("")}</tbody></table></div>`;
  }

  function matchRecordTable(matches) {
    return `<div class="table-shell"><table><thead><tr><th class="numeric">Rank</th><th>Date</th><th>Match</th><th class="numeric">Score</th><th class="numeric">Combined NR</th><th class="hide-mobile">Competition</th></tr></thead><tbody>${matches.map((match, index) => `<tr>
      <td class="rank-cell numeric">${index + 1}</td><td>${validDate(match.date)}</td><td>${teamLink(match.code1, match.team1)} <span class="muted">v</span> ${teamLink(match.code2, match.team2)}</td><td class="numeric"><span class="score">${escapeHTML(match.score).replace("-", "–")}</span></td><td class="numeric"><span class="rating-main">${rating(match.combined)}</span><span class="rating-sub">mean ${rating(match.combined_mean)} · joint SE ${rating(match.combined_se)}</span></td><td class="hide-mobile">${escapeHTML(match.tournament)}</td>
    </tr>`).join("")}</tbody></table></div>`;
  }

  function renderRecords() {
    setTitle("Records");
    content.innerHTML = `
      <div class="page">
        <header class="page-heading"><div><p class="eyebrow">One peak per nation · every match instance</p><h1>Records</h1></div><p class="lede">These are network records, not raw posterior means. The uncertainty penalty and opponent-breadth shrinkage stop tiny early pools and isolated regional loops dominating the list.</p></header>
        <div class="record-tabs"><button class="button button-dark" data-record="peaks" aria-pressed="true">Nation peaks</button><button class="button" data-record="matches" aria-pressed="false">Top matches</button></div>
        <div id="record-note" class="record-note"></div>
        <div id="record-table"></div>
        <div class="pagination"><span id="record-count" class="muted small"></span><button id="record-more" class="button">Show more</button></div>
      </div>`;
    let view = "peaks";
    let shown = 25;
    const update = () => {
      const source = view === "peaks" ? summary.peaks : summary.top_matches;
      const visible = source.slice(0, shown);
      document.getElementById("record-note").innerHTML = view === "peaks"
        ? `<strong>1×</strong><div><b>One maximum per canonical nation.</b> Successor histories are joined; a strict improvement is required to replace the earlier peak.</div>`
        : `<strong>Q</strong><div><b>Every eligible match instance is ranked.</b> Q is the two breadth-adjusted means minus 1.645 times their joint standard error; repeat pairings are not deduplicated.</div>`;
      document.getElementById("record-table").innerHTML = view === "peaks" ? peakTable(visible) : matchRecordTable(visible);
      document.getElementById("record-count").textContent = `Showing ${number(visible.length)} of ${number(source.length)}`;
      document.getElementById("record-more").hidden = shown >= source.length;
    };
    document.querySelectorAll("[data-record]").forEach((button) => button.addEventListener("click", () => {
      view = button.dataset.record;
      shown = 25;
      document.querySelectorAll("[data-record]").forEach((peer) => {
        const active = peer === button;
        peer.setAttribute("aria-pressed", String(active));
        peer.classList.toggle("button-dark", active);
      });
      update();
    }));
    document.getElementById("record-more").addEventListener("click", () => { shown += 25; update(); });
    update();
  }

  async function renderPredict() {
    setTitle("Predict a match");
    loading("Loading the current covariance state…");
    const state = await getJSON("data/state.json");
    const teams = summary.current;
    const defaultA = teams.find((team) => team.code === "ES") || teams[0];
    const defaultB = teams.find((team) => team.code === "AR") || teams[1];
    const options = (selected) => teams.map((team) => `<option value="${escapeHTML(team.code)}" ${team.code === selected ? "selected" : ""}>${escapeHTML(team.nation)} · ${rating(team.rating)}</option>`).join("");
    content.innerHTML = `
      <div class="page">
        <header class="page-heading"><div><p class="eyebrow">Current-state calculator</p><h1>Predict a match</h1></div><p class="lede">Choose two active teams, venue and match class. This uses the full current covariance matrix, integrates rating uncertainty, then applies the held-out friendly or competitive temperature.</p></header>
        <div class="predictor">
          <div class="team-picker"><p class="eyebrow">Team one</p><select id="predict-a" aria-label="Team one">${options(defaultA.code)}</select></div>
          <div class="versus" aria-hidden="true">v</div>
          <div class="team-picker"><p class="eyebrow">Team two</p><select id="predict-b" aria-label="Team two">${options(defaultB.code)}</select></div>
        </div>
        <div class="toolbar section">
          <div class="field"><label for="predict-venue">Venue</label><select id="predict-venue"><option value="0">Neutral</option><option value="1">Team one at home</option><option value="-1">Team two at home</option></select></div>
          <div class="field"><label for="predict-class">Match class</label><select id="predict-class"><option value="competitive">Competitive</option><option value="friendly">Friendly</option></select></div>
        </div>
        <div id="forecast"></div>
      </div>`;
    const byCode = new Map(summary.teams.map((team) => [team.code, team]));
    const stateIndex = new Map(state.codes.map((code, index) => [code, index]));
    const covariance = state.covariance;
    const n = state.codes.length;
    const cov = (i, j) => covariance[i * n + j];
    const logistic = (value) => 1 / (1 + Math.pow(10, -value / 400));
    const update = () => {
      const codeA = document.getElementById("predict-a").value;
      const codeB = document.getElementById("predict-b").value;
      const target = document.getElementById("forecast");
      if (codeA === codeB) {
        target.innerHTML = `<div class="error-panel"><h2>Choose two different teams</h2><p>A team cannot play itself.</p></div>`;
        return;
      }
      const i = stateIndex.get(codeA);
      const j = stateIndex.get(codeB);
      const teamA = byCode.get(codeA);
      const teamB = byCode.get(codeB);
      const home = Number(document.getElementById("predict-venue").value);
      const matchClass = document.getElementById("predict-class").value;
      const variance = Math.max(0, cov(i, i) + cov(j, j) - 2 * cov(i, j));
      const difference = state.scale * (state.means[i] - state.means[j]) + state.home * home;
      const base = [0, 0, 0];
      state.nodes.forEach((node, index) => {
        const sampled = difference + Math.sqrt(2 * variance) * state.scale * node;
        const expected = logistic(sampled);
        const draw = state.draw * 4 * expected * (1 - expected);
        const values = [expected - draw / 2, draw, 1 - expected - draw / 2];
        values.forEach((value, outcome) => { base[outcome] += state.weights[index] * value; });
      });
      const temperature = matchClass === "friendly" ? state.friendly_temperature : state.competitive_temperature;
      const powered = base.map((value) => Math.pow(Math.max(1e-15, value), temperature));
      const total = powered.reduce((sum, value) => sum + value, 0);
      const probabilities = powered.map((value) => value / total);
      const max = Math.max(...probabilities);
      const jointSE = Math.sqrt(Math.max(0, cov(i, i) + cov(j, j) + 2 * cov(i, j)));
      const combined = teamA.mean + teamB.mean - confidenceZ * jointSE;
      const labels = [`${teamA.nation} win`, "Draw", `${teamB.nation} win`];
      target.innerHTML = `<section class="forecast" aria-live="polite">
        <div class="forecast-title"><div><p class="eyebrow">Calibrated forecast</p><h2>${escapeHTML(teamA.nation)} v ${escapeHTML(teamB.nation)}</h2></div><span>${escapeHTML(matchClass)} · ${home === 0 ? "neutral" : home === 1 ? `${escapeHTML(teamA.nation)} home` : `${escapeHTML(teamB.nation)} home`}</span></div>
        <div class="forecast-bars">${probabilities.map((value, index) => `<div class="forecast-outcome ${value === max ? "is-top" : ""}"><span>${escapeHTML(labels[index])}</span><strong>${percent(value)}</strong></div>`).join("")}</div>
        <div class="forecast-meta"><span>${escapeHTML(teamA.nation)} NR <b>${rating(teamA.rating)}</b></span><span>${escapeHTML(teamB.nation)} NR <b>${rating(teamB.rating)}</b></span><span>Combined matchup NR <b>${rating(combined)}</b></span><span>Difference SD <b>${rating(Math.sqrt(variance))}</b></span></div>
      </section>`;
    };
    ["predict-a", "predict-b", "predict-venue", "predict-class"].forEach((id) => document.getElementById(id).addEventListener("change", update));
    update();
  }

  function ratingChart(history, nation) {
    if (!history || history.length < 2) return `<div class="empty">A rating line begins after 30 matches.</div>`;
    const width = 1000;
    const height = 330;
    const pad = { left: 58, right: 18, top: 20, bottom: 36 };
    const time = (date) => {
      const [y, m, d] = date.split("-").map(Number);
      return y + Math.max(0, m - 1) / 12 + Math.max(0, d - 1) / 365;
    };
    const xs = history.map((point) => time(point.date));
    const ys = history.map((point) => point.rating);
    const minX = Math.min(...xs);
    const maxX = Math.max(...xs);
    const rawMin = Math.min(...ys);
    const rawMax = Math.max(...ys);
    const minY = Math.floor((rawMin - 20) / 50) * 50;
    const maxY = Math.ceil((rawMax + 20) / 50) * 50;
    const x = (value) => pad.left + (value - minX) / Math.max(1, maxX - minX) * (width - pad.left - pad.right);
    const y = (value) => height - pad.bottom - (value - minY) / Math.max(1, maxY - minY) * (height - pad.top - pad.bottom);
    const coordinates = history.map((point, index) => `${x(xs[index]).toFixed(2)},${y(point.rating).toFixed(2)}`);
    const line = coordinates.join(" ");
    const area = `${x(minX)},${height - pad.bottom} ${line} ${x(maxX)},${height - pad.bottom}`;
    const yTicks = Array.from({ length: 5 }, (_, index) => minY + (maxY - minY) * index / 4);
    const xTicks = Array.from({ length: 5 }, (_, index) => minX + (maxX - minX) * index / 4);
    const last = history[history.length - 1];
    const peak = history.reduce((best, point) => point.rating > best.rating ? point : best, history[0]);
    return `<div class="chart-shell">
      <svg class="rating-chart" viewBox="0 0 ${width} ${height}" role="img" aria-labelledby="chart-title chart-desc" preserveAspectRatio="none">
        <title id="chart-title">${escapeHTML(nation)} network rating history</title><desc id="chart-desc">Rating after each match from ${validDate(history[0].date)} to ${validDate(last.date)}. Peak ${rating(peak.rating)} on ${validDate(peak.date)}.</desc>
        <defs><linearGradient id="rating-gradient" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#ef725f"/><stop offset="1" stop-color="#ef725f" stop-opacity="0"/></linearGradient></defs>
        ${yTicks.map((tick) => `<line class="grid" x1="${pad.left}" y1="${y(tick)}" x2="${width - pad.right}" y2="${y(tick)}"/><text x="${pad.left - 10}" y="${y(tick) + 4}" text-anchor="end">${rating(tick)}</text>`).join("")}
        ${xTicks.map((tick) => `<text x="${x(tick)}" y="${height - 10}" text-anchor="middle">${Math.round(tick)}</text>`).join("")}
        <polygon class="area" points="${area}"/><polyline class="line" points="${line}"/>
        <circle cx="${x(xs[xs.length - 1])}" cy="${y(last.rating)}" r="5" fill="#ef725f"><title>${validDate(last.date)} · ${rating(last.rating)}</title></circle>
      </svg>
      <div class="chart-summary"><span>First eligible: ${validDate(history[0].date)} · ${rating(history[0].rating)}</span><span>Peak: ${validDate(peak.date)} · ${rating(peak.rating)}</span><span>Latest appearance: ${validDate(last.date)} · ${rating(last.rating)}</span></div>
    </div>`;
  }

  async function renderTeam(code) {
    loading("Loading the team history…");
    const page = await getJSON(`data/teams/${encodeURIComponent(code)}.json`);
    const team = page.team;
    setTitle(team.nation);
    content.innerHTML = `
      <div class="page">
        <section class="team-hero">
          <div><p class="eyebrow">${team.rank ? `Current world no. ${team.rank}` : "Historical team record"}</p><h1>${escapeHTML(team.nation)}</h1></div>
          <div class="team-rating"><strong>${rating(team.rating)}</strong><span>network rating · SE ${rating(team.se)}</span></div>
        </section>
        <div class="team-stats">
          <div><span>Matches</span><strong>${number(team.matches)}</strong></div><div><span>Record</span><strong>${team.wins}–${team.draws}–${team.losses}</strong></div><div><span>Goals</span><strong>${team.gf}–${team.ga}</strong></div><div><span>Opponent breadth</span><strong>${number(team.breadth, 1)}</strong></div><div><span>All-time peak</span><strong>${team.peak ? rating(team.peak.rating) : "—"}</strong></div>
        </div>
        <section class="section"><div class="section-heading"><div><p class="eyebrow">After-match history</p><h2>Network rating</h2></div></div>${ratingChart(page.history, team.nation)}</section>
        <section class="section"><div class="section-heading"><div><p class="eyebrow">Complete ledger</p><h2>Matches</h2></div><a class="button button-quiet" href="#/matches?team=${encodeURIComponent(team.code)}">Open in explorer →</a></div><div id="team-matches"></div><div class="pagination"><span id="team-count" class="muted small"></span><button id="team-more" class="button">Show more</button></div></section>
      </div>`;
    let shown = 100;
    const update = () => {
      const matches = page.matches.slice(0, shown);
      document.getElementById("team-matches").innerHTML = `<div class="table-shell"><table><thead><tr><th>Date</th><th>Opponent</th><th class="numeric">Score</th><th>Result</th><th class="hide-mobile">Competition</th><th class="numeric hide-mobile">Post NR</th></tr></thead><tbody>${matches.map((match) => `<tr><td>${validDate(match.date)}</td><td>${teamLink(match.opponent_code, match.opponent)}</td><td class="numeric"><span class="score">${match.gf}–${match.ga}</span></td><td>${formHTML([match.result])}</td><td class="hide-mobile">${escapeHTML(match.tournament)}</td><td class="numeric hide-mobile">${rating(match.post)}</td></tr>`).join("")}</tbody></table></div>`;
      document.getElementById("team-count").textContent = `Showing ${number(matches.length)} of ${number(page.matches.length)}`;
      document.getElementById("team-more").hidden = shown >= page.matches.length;
    };
    document.getElementById("team-more").addEventListener("click", () => { shown += 100; update(); });
    update();
  }

  function renderMethodology() {
    setTitle("Methodology");
    const p = summary.parameters;
    content.innerHTML = `
      <article class="page page-narrow prose">
        <p class="eyebrow">Frozen deployment specification</p><h1>Methodology</h1>
        <p class="lede">The predictive system is an Elo-linked dynamic Bayesian opponent network. It retains the familiar base-10 Elo curve while replacing one scalar per team with a joint Gaussian state <code>r ~ N(μ, Σ)</code>.</p>
        <div class="callout"><b>Why “network” matters:</b> a match measures a rating difference, not an absolute level. Keeping the full covariance lets evidence travel through common opponents and preserves uncertainty in isolated historical components.</div>

        <h2>1. Era-adjusted Elo link</h2>
        <p>For team 1 against team 2, with <code>h = +1</code> at home, <code>−1</code> away and zero neutral:</p>
        <div class="formula">δ = a(y)(μ₁ − μ₂) + H(y)h<br>E = 1 / (1 + 10^(−δ/400))</div>
        <p>The knot years are 1900, 1930, 1960, 1990 and 2020. The gap scale is log-linearly interpolated, home advantage linearly, and the even-strength draw rate in a bounded logit coordinate.</p>
        <div class="table-shell parameter-table"><table><thead><tr><th>Year</th><th class="numeric">Gap scale</th><th class="numeric">Effective divisor</th><th class="numeric">Home</th><th class="numeric">Draw rate</th></tr></thead><tbody>${p.knot_years.map((year, index) => `<tr><td>${year}${index === 4 ? "+" : ""}</td><td class="numeric">${number(p.calibration_scale[index], 6)}</td><td class="numeric">${number(400 / p.calibration_scale[index], 3)}</td><td class="numeric">${number(p.home_advantage[index], 3)}</td><td class="numeric">${percent(p.draw_probability[index])}</td></tr>`).join("")}</tbody></table></div>

        <h2>2. Win, draw and loss</h2>
        <p>At a fixed effective gap, the three outcomes preserve the Elo fractional-score expectation exactly:</p>
        <div class="formula">D = pD(y) · 4E(1 − E)<br>W = E − D/2<br>L = 1 − E − D/2</div>
        <p>Pre-match difference uncertainty <code>a(y)²(Σ₁₁ + Σ₂₂ − 2Σ₁₂)</code> is integrated with 11-point Gauss–Hermite quadrature. Finally, each probability is raised to temperature <code>T</code> and renormalised: <b>${number(p.forecast_temperature.friendly, 10)}</b> for friendlies and <b>${number(p.forecast_temperature.competitive, 10)}</b> for competitive matches.</p>

        <h2>3. Era-normalised goal margin</h2>
        <p>The raw margin is adjusted against the preceding 20 calendar years' decisive scoring environment. With a 20-match prior at excess margin 1.10:</p>
        <div class="formula">C(y) = [20·1.10 + Σ(min(mᵣ,7)−1)] / (20 + N)<br>m* = min[7, 1 + (min(m,7)−1)(1.10/max(0.10,C))^${number(p.goal_margin.environment_power, 10)}]</div>
        <p>The information landmarks are draw <b>${number(p.goal_margin.draw, 6)}</b>, one goal <b>1</b>, two <b>${number(p.goal_margin.two, 6)}</b>, three <b>${number(p.goal_margin.three, 6)}</b>, then <b>${number(p.goal_margin.tail, 6)}</b> per additional effective goal.</p>

        <h2>4. Dynamic network update</h2>
        <p>Before each participant's match, independent variance grows by <code>${number(p.network.drift_sd, 10)}² × elapsed years</code>. A debutant starts with SD <b>${number(p.network.prior_sd, 0)}</b>. Let <code>x=e₁−e₂</code>, <code>v=Σx</code>, <code>V=xᵀΣx</code>, <code>β=a(y)ln(10)/400</code>, and <code>λ=${number(p.network.quality_scale, 10)}G(m)</code>.</p>
        <div class="formula">d = 1 + λβ²E(1−E)V<br>μ′ = μ + v · λβ(S−E)/d<br>Σ′ = Σ − vvᵀ · λβ²E(1−E)/d</div>
        <p>All five competition levels have state-information ratio <b>1</b>. The bake-off found no stable held-out gain from unequal update levels; match seriousness survives in the two forecast temperatures.</p>

        <h2>5. Starting teams</h2>
        <p>A newcomer starts from the median of active mature teams, falling back to established teams. If the reference pool is empty it starts at latent zero.</p>
        <div class="formula">μdebut = median(active pool) ${p.debut.offset < 0 ? "−" : "+"} ${number(Math.abs(p.debut.offset), 10)} ${p.debut.pool_slope < 0 ? "−" : "+"} ${number(Math.abs(p.debut.pool_slope), 10)} ln[(A+10)/50]</div>

        <h2>6. The displayed network rating</h2>
        <p>Predictions use <code>μ</code> and <code>Σ</code> directly. The record table adds a separate conservative display layer. Opponent weights decay with an eight-year half-life. Their Kish effective count <code>N</code> gives breadth reliability <code>ρ=N/(N+4)</code>. The baseline <code>B</code> is the mean latent strength of the active top ten.</p>
        <div class="formula">Mᵢ = 2000 + ρᵢ(μᵢ − B)<br>NRᵢ = Mᵢ − 1.64485362695 √Σᵢᵢ<br>Qᵢⱼ = Mᵢ + Mⱼ − 1.64485362695 √(Σᵢᵢ+Σⱼⱼ+2Σᵢⱼ)</div>
        <p>The breadth factor shrinks the mean deviation only, not the standard error. Every match instance is eligible for <code>Q</code> once both teams have 30 prior matches; repeat pairings are retained.</p>

        <h2>Validation</h2>
        <p>Rolling-origin held-out evaluation covered ${number(summary.validation.matches)} matches from 1960–2026. The release model scored log loss <b>${number(summary.validation.log_loss, 6)}</b>, Brier <b>${number(summary.validation.brier, 6)}</b>, RPS <b>${number(summary.validation.rps, 6)}</b> and accuracy <b>${percent(summary.validation.accuracy)}</b>. The published WFE baseline's log loss was <b>${number(summary.validation.published_wfe_log_loss, 6)}</b>.</p>
        <div class="callout">The frozen 2026 parameter set is fitted on all results through the release ledger, so it does not itself have a future test block. The model class—not those final fitted decimals—earned its selection on nested historical test blocks.</div>
      </article>`;
  }

  function renderAbout() {
    setTitle("About and updates");
    const update = summary.meta.source_update || {};
    content.innerHTML = `
      <div class="page page-narrow">
        <p class="eyebrow">Provenance · automation · limitations</p><h1>About</h1>
        <p class="lede">This is an independent, reproducible rating site built from public World Football Elo Ratings TSV ledgers and a frozen model selected in the Great Elo Bake-off.</p>
        <section class="section split">
          <div class="panel"><p class="eyebrow">Current build</p><h2>${validDate(summary.meta.results_through)}</h2><p>${number(summary.meta.matches)} unique matches across ${number(summary.meta.teams)} canonical successor histories.</p><p class="muted small">Source check: ${update.source_checked_at ? validDate(update.source_checked_at.slice(0, 10)) : "bundled release snapshot"}<br>Mode: ${escapeHTML(update.mode || "bundled snapshot")}<br>Changed pages: ${number(update.pages_changed || 0)}</p></div>
          <div class="panel panel-dark"><p class="eyebrow">Automatic update</p><h2>Fail closed, keep the last good site.</h2><p class="muted">The scheduled workflow checks the current ranking and reference TSVs daily, refreshes changed team pages, performs a full periodic reconciliation, validates field counts and source size, replays all history, runs tests, then deploys the static artifact.</p></div>
        </section>
        <article class="section prose">
          <h2>Source and attribution</h2>
          <p>Historical result rows and reference labels come from <a href="https://eloratings.net/" rel="external">World Football Elo Ratings</a>. Its published baseline formula is described on the <a href="https://eloratings.net/about" rel="external">methodology page</a>. This project neither republishes that site's interface nor uses its JavaScript; it parses the public headerless TSV ledgers and applies a separately developed model.</p>
          <h2>What updates automatically</h2>
          <p>New and corrected source results are incorporated. The full state is replayed because debut priors, covariance, margin environment and opponent breadth are path-dependent. The fitted constants do <em>not</em> change during a routine update. A future re-fit must be a separate, reviewed bake-off.</p>
          <h2>What the model does not know</h2>
          <p>It does not use line-ups, player availability, injuries, red cards, travel, rest, tactical matchups, weather or betting markets. Its probabilities describe the historical-information model, not certainty and not a recommendation to wager.</p>
          <h2>Data integrity</h2>
          <p>The release source digest is <code>${escapeHTML(summary.meta.source_sha256)}</code>. The build manifest hashes every deployed file. If a source page is empty, changes schema, or shrinks beyond the safety tolerance, the workflow stops before replacing the previous successful deployment.</p>
        </article>
      </div>`;
  }

  function renderNotFound() {
    setTitle("Not found");
    content.innerHTML = `<div class="error-panel"><p class="eyebrow">404</p><h2>That page is outside the network.</h2><p>Return to the current rankings or explore the full match ledger.</p><a class="button button-dark" href="#/">Go home</a></div>`;
  }

  async function route() {
    const current = parseRoute();
    setActiveNav(current.section);
    try {
      if (!summary) [summary, catalog] = await Promise.all([getJSON("data/summary.json"), getJSON("data/catalog.json")]);
      switch (current.section) {
        case "home": renderHome(); break;
        case "rankings": renderRankings(); break;
        case "matches": await renderMatches(current); break;
        case "records": renderRecords(); break;
        case "predict": await renderPredict(); break;
        case "team": current.value ? await renderTeam(current.value) : renderNotFound(); break;
        case "methodology": renderMethodology(); break;
        case "about": renderAbout(); break;
        default: renderNotFound();
      }
    } catch (error) {
      console.error(error);
      content.innerHTML = `<div class="error-panel" role="alert"><p class="eyebrow">Build data unavailable</p><h2>The static rating files could not be loaded.</h2><p>${escapeHTML(error.message)}</p><button class="button button-dark" type="button" id="retry">Retry</button></div>`;
      document.getElementById("retry")?.addEventListener("click", () => { dataCache.clear(); summary = null; route(); });
    }
  }

  menuButton.addEventListener("click", () => {
    const open = !nav.classList.contains("is-open");
    nav.classList.toggle("is-open", open);
    menuButton.setAttribute("aria-expanded", String(open));
  });
  window.addEventListener("hashchange", route);
  route();
})();
