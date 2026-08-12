(() => {
  "use strict";

  const DATA = "data/";
  const content = document.getElementById("club-content");
  const cache = new Map();
  const MATCH_FIELDS = [
    "id", "date", "home", "away", "home_goals", "away_goals",
    "competition", "kind", "home_tier", "away_tier", "neutral",
    "cross_border", "status", "leg", "tie_key", "aggregate_before_home",
    "aggregate_after_home", "aggregate_weight", "evidence_weight",
    "pre_home_rating", "pre_away_rating", "post_home_rating",
    "post_away_rating", "home_probability", "draw_probability",
    "away_probability", "home_rating_delta", "surprise", "source",
    "source_ref", "round",
  ];

  let bootstrap = null;
  let clubCatalog = null;
  let clubMap = null;

  const escapeHTML = (value) => String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");

  const number = (value, digits = 0) => {
    const numeric = Number(value);
    if (!Number.isFinite(numeric)) return "—";
    return numeric.toLocaleString("en", {
      useGrouping: true,
      minimumFractionDigits: digits,
      maximumFractionDigits: digits,
    });
  };
  const rating = (value) => {
    const numeric = Number(value);
    if (!Number.isFinite(numeric)) return "—";
    return numeric.toLocaleString("en", {
      useGrouping: false,
      minimumFractionDigits: 1,
      maximumFractionDigits: 1,
    });
  };
  const percent = (value) => `${number(Number(value) * 100, 1)}%`;
  const signed = (value, digits = 1) => {
    const numeric = Number(value);
    return `${numeric > 0 ? "+" : ""}${number(numeric, digits)}`;
  };
  const slugLabel = (value) => String(value || "").replaceAll("_", " ").replaceAll("-", " ")
    .replace(/\b\w/g, (letter) => letter.toUpperCase());

  async function getJSON(path) {
    if (!cache.has(path)) {
      cache.set(path, fetch(`${DATA}${path}`).then(async (response) => {
        if (!response.ok) throw new Error(`${path} returned HTTP ${response.status}`);
        return response.json();
      }).catch((error) => {
        cache.delete(path);
        throw error;
      }));
    }
    return cache.get(path);
  }

  async function getClubs() {
    if (!clubCatalog) {
      clubCatalog = (await getJSON("clubs.json")).clubs;
      clubMap = new Map(clubCatalog.map((club) => [club.code, club]));
    }
    return clubCatalog;
  }

  function matchObject(row) {
    return Object.fromEntries(MATCH_FIELDS.map((field, index) => [field, row[index]]));
  }

  function loading(label = "Loading club data…") {
    content.innerHTML = `<section class="loading-card" role="status"><span class="spinner" aria-hidden="true"></span><div><strong>${escapeHTML(label)}</strong><p>The archive is split into small static files, so only the requested view is downloaded.</p></div></section>`;
  }

  function fail(error) {
    console.error(error);
    content.innerHTML = `<section class="error-card" role="alert"><div><p class="eyebrow">Could not open this view</p><h2>The club archive did not load.</h2><p>${escapeHTML(error?.message || error)}</p><button class="button" type="button" id="retry-route">Try again</button></div></section>`;
    document.getElementById("retry-route")?.addEventListener("click", () => route(true));
  }

  function heading(eyebrow, title, description, aside = "") {
    return `<header class="page-heading"><div><p class="eyebrow">${escapeHTML(eyebrow)}</p><h1>${title}</h1><p class="lede">${description}</p></div>${aside}</header>`;
  }

  function metricCards(cards) {
    return `<section class="stat-grid">${cards.map((card) => `<article class="stat-card"><span>${escapeHTML(card.label)}</span><strong>${escapeHTML(card.value)}</strong><small>${escapeHTML(card.note || "")}</small></article>`).join("")}</section>`;
  }

  function clubLink(code, name) {
    return `<a class="team-link" href="#/club/${encodeURIComponent(code)}">${escapeHTML(name)}</a>`;
  }

  function clubName(code) {
    return clubMap?.get(code)?.name || code;
  }

  function clubCountry(code) {
    return clubMap?.get(code)?.country_name || slugLabel(clubMap?.get(code)?.country || "");
  }

  function selectOptions(items, selected, valueKey, label) {
    return items.map((item) => {
      const value = typeof valueKey === "function" ? valueKey(item) : item[valueKey];
      const text = label(item);
      return `<option value="${escapeHTML(value)}"${String(value) === String(selected) ? " selected" : ""}>${escapeHTML(text)}</option>`;
    }).join("");
  }

  function probabilityMarkup(match) {
    const home = Math.max(0, Number(match.home_probability));
    const draw = Math.max(0, Number(match.draw_probability));
    const away = Math.max(0, Number(match.away_probability));
    return `<div class="match-detail" aria-label="Pre-match probabilities"><div class="probability-bar" style="--home:${home}fr;--draw:${draw}fr;--away:${away}fr"><span></span><span></span><span></span></div><div class="probability-labels"><span>H ${percent(home)}</span><span>D ${percent(draw)}</span><span>A ${percent(away)}</span></div></div>`;
  }

  function matchRows(rows, limit = 500) {
    if (!rows.length) return `<div class="empty">No matches meet these filters.</div>`;
    const visible = rows.slice(0, limit);
    return `<div class="result-note">Showing ${number(visible.length)} of ${number(rows.length)} matches. Probabilities and ratings are frozen before the listed match.</div><div class="table-wrap"><table><thead><tr><th>Date / competition</th><th>Match</th><th class="numeric">Pre-match rating</th><th>Probabilities</th><th class="numeric">Movement</th><th class="hide-mobile">Context / source</th></tr></thead><tbody>${visible.map((match) => {
      const aggregate = match.leg === 2 && match.aggregate_before_home !== null;
      const aggregateText = aggregate
        ? `Aggregate ${signed(match.aggregate_before_home, 0)} → ${signed(match.aggregate_after_home, 0)} from home side; ${number(Number(match.aggregate_weight) * 100, 1)}% leg weight`
        : "";
      const status = match.status === "P" ? " · penalties treated as draw" : (match.status === "E" ? " · extra time" : "");
      return `<tr><td><strong>${escapeHTML(match.date)}</strong><span class="subline">${escapeHTML(match.competition)} · ${escapeHTML(slugLabel(match.kind))}</span></td><td class="team-cell">${clubLink(match.home, clubName(match.home))}<span class="score"> ${escapeHTML(match.home_goals)}–${escapeHTML(match.away_goals)} </span>${clubLink(match.away, clubName(match.away))}<span class="subline">${match.neutral ? "Neutral" : "Home venue"}${match.cross_border ? " · cross-border" : ""}${status}</span></td><td class="numeric"><strong>${rating(match.pre_home_rating)}</strong> / <strong>${rating(match.pre_away_rating)}</strong><span class="subline">home / away</span></td><td>${probabilityMarkup(match)}</td><td class="numeric movement ${Number(match.home_rating_delta) >= 0 ? "positive" : "negative"}">${signed(match.home_rating_delta, 1)}<span class="subline">home-side update</span></td><td class="hide-mobile"><span class="badge${aggregate ? " aggregate" : ""}">${aggregate ? `Leg 2 · ${number(Number(match.aggregate_weight) * 100, 0)}%` : (match.cross_border ? "Cross-border" : `Tier ${Math.max(match.home_tier, match.away_tier)}`)}</span><span class="subline" title="${escapeHTML(match.source_ref)}">${escapeHTML(match.source)} · ${escapeHTML(match.source_ref)}</span>${aggregate ? `<span class="subline">${escapeHTML(aggregateText)}</span>` : ""}</td></tr>`;
    }).join("")}</tbody></table></div>`;
  }

  function lineChart(series, options = {}) {
    const width = 920;
    const height = 320;
    const margin = { left: 58, right: 20, top: 20, bottom: 38 };
    const points = series.flatMap((item) => item.points).filter((point) => Number.isFinite(point[0]) && Number.isFinite(point[1]));
    if (points.length < 2) return `<div class="empty">Not enough annual snapshots for a chart.</div>`;
    let minX = Math.min(...points.map((point) => point[0]));
    let maxX = Math.max(...points.map((point) => point[0]));
    let minY = Math.min(...points.map((point) => point[1]));
    let maxY = Math.max(...points.map((point) => point[1]));
    if (minX === maxX) maxX += 1;
    const yPad = Math.max(30, (maxY - minY) * .12);
    minY = Math.floor((minY - yPad) / 50) * 50;
    maxY = Math.ceil((maxY + yPad) / 50) * 50;
    const x = (value) => margin.left + ((value - minX) / (maxX - minX)) * (width - margin.left - margin.right);
    const y = (value) => margin.top + ((maxY - value) / (maxY - minY)) * (height - margin.top - margin.bottom);
    const grids = Array.from({ length: 5 }, (_, index) => {
      const value = minY + ((maxY - minY) * index) / 4;
      return `<line class="grid" x1="${margin.left}" x2="${width - margin.right}" y1="${y(value)}" y2="${y(value)}"></line><text class="axis-label" x="${margin.left - 9}" y="${y(value) + 4}" text-anchor="end">${Math.round(value)}</text>`;
    }).join("");
    const yearTicks = Array.from(new Set([minX, Math.round((minX + maxX) / 2), maxX])).map((value) => `<text class="axis-label" x="${x(value)}" y="${height - 10}" text-anchor="middle">${value}</text>`).join("");
    const paths = series.map((item, index) => {
      const ordered = [...item.points].sort((a, b) => a[0] - b[0]);
      const d = ordered.map((point, pointIndex) => `${pointIndex ? "L" : "M"}${x(point[0]).toFixed(1)},${y(point[1]).toFixed(1)}`).join(" ");
      return `<path class="line-${index ? "b" : "a"}" d="${d}"></path>`;
    }).join("");
    return `<div class="chart-wrap"><svg class="chart" viewBox="0 0 ${width} ${height}" role="img" aria-label="${escapeHTML(options.label || "Annual rating history")}">${grids}${yearTicks}${paths}</svg>${series.length > 1 ? `<div class="chart-legend">${series.map((item) => `<span>${escapeHTML(item.name)}</span>`).join("")}</div>` : ""}</div>`;
  }

  async function rankingsPage() {
    loading("Loading global rankings…");
    const [rankings, associations] = await Promise.all([
      getJSON("rankings.json"),
      getJSON("associations.json"),
      getClubs(),
    ]);
    const meta = bootstrap.meta;
    const continents = [...new Set(rankings.clubs.map((club) => club.continent))].sort();
    const countries = [...new Map(rankings.clubs.map((club) => [club.country, club.country_name])).entries()]
      .sort((a, b) => a[1].localeCompare(b[1]));
    content.innerHTML = `<div class="page"><section class="hero-strip"><div><p class="eyebrow">Independent global club model</p><h1>One connected ranking across club football.</h1><p class="lede">Domestic leagues, deep tiers, cups and cross-border competitions feed one uncertainty-adjusted rating. Association coefficients bridge otherwise separate league systems.</p></div><div class="hero-metrics"><article><strong>${number(meta.matches)}</strong><span>unique competitive matches</span></article><article><strong>${number(meta.active_clubs)}</strong><span>currently active clubs</span></article><article><strong>${number(meta.associations)}</strong><span>association systems</span></article><article><strong>${number(meta.explicit_second_legs)}</strong><span>aggregate-annotated second legs</span></article></div></section>${heading("Current state", "Global club rankings", `Active means a result in the last ${rankings.active_days} days. The public rating is the model mean minus an uncertainty allowance; low-evidence clubs are therefore ranked cautiously.`, `<p class="as-of"><strong>${escapeHTML(meta.results_through)}</strong>results through</p>`)}<section class="panel"><div class="controls"><div class="tab-row" aria-label="Ranking type"><button type="button" data-mode="clubs" aria-pressed="true">Clubs</button><button type="button" data-mode="associations" aria-pressed="false">Associations</button></div><div class="field grow club-control"><label for="ranking-search">Find a club</label><input id="ranking-search" type="search" placeholder="Name or country"></div><div class="field club-control"><label for="ranking-continent">Continent</label><select id="ranking-continent"><option value="">All continents</option>${continents.map((value) => `<option>${escapeHTML(value)}</option>`).join("")}</select></div><div class="field club-control"><label for="ranking-country">Association</label><select id="ranking-country"><option value="">All associations</option>${countries.map(([value, label]) => `<option value="${escapeHTML(value)}">${escapeHTML(label)}</option>`).join("")}</select></div></div><div id="ranking-table"></div></section></div>`;

    const table = document.getElementById("ranking-table");
    const search = document.getElementById("ranking-search");
    const continent = document.getElementById("ranking-continent");
    const country = document.getElementById("ranking-country");
    let mode = "clubs";
    function render() {
      document.querySelectorAll(".club-control").forEach((element) => { element.hidden = mode !== "clubs"; });
      if (mode === "associations") {
        table.innerHTML = `<div class="result-note">The coefficient is the association component added to every club’s residual. It updates only in cross-border matches.</div><div class="table-wrap"><table><thead><tr><th class="rank">Rank</th><th>Association</th><th class="numeric">Coefficient</th><th class="numeric">Index</th><th class="numeric">Uncertainty</th><th class="numeric">Cross-border updates</th></tr></thead><tbody>${associations.associations.map((row) => `<tr><td class="rank">${row.rank}</td><td><strong>${escapeHTML(row.name)}</strong><span class="subline">${escapeHTML(row.continent)}</span></td><td class="numeric rating">${signed(row.coefficient, 1)}</td><td class="numeric">${rating(row.index)}</td><td class="numeric">±${number(row.se, 1)}</td><td class="numeric">${number(row.cross_border_updates)}</td></tr>`).join("")}</tbody></table></div>`;
        return;
      }
      const query = search.value.trim().toLocaleLowerCase();
      const rows = rankings.clubs.filter((club) => (!query || `${club.name} ${club.country_name}`.toLocaleLowerCase().includes(query)) && (!continent.value || club.continent === continent.value) && (!country.value || club.country === country.value));
      const visible = rows.slice(0, 750);
      table.innerHTML = `<div class="result-note">Showing ${number(visible.length)} of ${number(rows.length)} matching active clubs. “Mean” is used for forecasts; “rating” includes the uncertainty deduction.</div><div class="table-wrap"><table><thead><tr><th class="rank">Rank</th><th>Club</th><th class="numeric">Rating</th><th class="numeric">Mean</th><th class="numeric">Uncertainty</th><th class="numeric hide-mobile">Matches</th><th class="hide-mobile">Latest tier / result</th></tr></thead><tbody>${visible.map((club) => `<tr><td class="rank">${club.rank}</td><td class="team-cell">${clubLink(club.code, club.name)}<span class="subline">${escapeHTML(club.country_name)} · ${escapeHTML(club.continent)}${club.provisional ? " · provisional" : ""}</span></td><td class="numeric rating">${rating(club.rating)}</td><td class="numeric">${rating(club.mean)}</td><td class="numeric">±${number(club.se, 1)}</td><td class="numeric hide-mobile">${number(club.matches)}</td><td class="hide-mobile"><span class="badge">Tier ${club.tier}</span><span class="subline">${escapeHTML(club.last)}</span></td></tr>`).join("")}</tbody></table></div>`;
    }
    document.querySelectorAll("[data-mode]").forEach((button) => button.addEventListener("click", () => {
      mode = button.dataset.mode;
      document.querySelectorAll("[data-mode]").forEach((item) => item.setAttribute("aria-pressed", String(item === button)));
      render();
    }));
    [search, continent, country].forEach((control) => control.addEventListener(control === search ? "input" : "change", render));
    render();
  }

  async function historyPage() {
    loading("Loading historical ranking index…");
    const [index] = await Promise.all([getJSON("history/index.json"), getClubs()]);
    const latest = index.years.at(-1)?.year;
    content.innerHTML = `<div class="page">${heading("Year-opening snapshots", "Historical global rankings", "Each snapshot uses only matches completed before 1 January of that year. Eligibility follows the same 550-day activity window as the current table.")}<section class="panel"><div class="controls"><div class="field"><label for="history-year">Opening of year</label><select id="history-year">${[...index.years].reverse().map((row) => `<option value="${row.year}"${row.year === latest ? " selected" : ""}>${row.year} · ${number(row.clubs)} clubs</option>`).join("")}</select></div><div class="field grow"><label for="history-search">Find a club</label><input id="history-search" type="search" placeholder="Name or association"></div></div><div id="history-table"><div class="empty">Choose a year.</div></div></section></div>`;
    const year = document.getElementById("history-year");
    const search = document.getElementById("history-search");
    const target = document.getElementById("history-table");
    let rows = [];
    async function loadYear() {
      target.innerHTML = `<div class="empty">Loading ${escapeHTML(year.value)}…</div>`;
      rows = (await getJSON(`history/${year.value}.json`)).rankings;
      render();
    }
    function render() {
      const query = search.value.trim().toLocaleLowerCase();
      const filtered = rows.filter((row) => {
        const club = clubMap.get(row[1]);
        return !query || `${club?.name} ${club?.country_name}`.toLocaleLowerCase().includes(query);
      });
      const visible = filtered.slice(0, 750);
      target.innerHTML = `<div class="result-note">Opening state for ${escapeHTML(year.value)} · showing ${number(visible.length)} of ${number(filtered.length)} matching clubs.</div><div class="table-wrap"><table><thead><tr><th class="rank">Rank</th><th>Club</th><th class="numeric">Rating</th><th class="numeric">Mean</th><th class="numeric">Uncertainty</th><th class="numeric hide-mobile">Matches to date</th><th class="hide-mobile">Tier / latest result</th></tr></thead><tbody>${visible.map((row) => { const club = clubMap.get(row[1]); return `<tr><td class="rank">${row[0]}</td><td>${clubLink(row[1], club?.name || row[1])}<span class="subline">${escapeHTML(club?.country_name || "")}</span></td><td class="numeric rating">${rating(row[2])}</td><td class="numeric">${rating(row[3])}</td><td class="numeric">±${number(row[4], 1)}</td><td class="numeric hide-mobile">${number(row[5])}</td><td class="hide-mobile"><span class="badge">Tier ${row[6]}</span><span class="subline">${escapeHTML(row[7])}</span></td></tr>`; }).join("")}</tbody></table></div>`;
    }
    year.addEventListener("change", loadYear);
    search.addEventListener("input", render);
    await loadYear();
  }

  async function clubsPage() {
    loading("Loading the club catalog…");
    const clubs = await getClubs();
    const countries = [...new Map(clubs.map((club) => [club.country, club.country_name])).entries()].sort((a, b) => a[1].localeCompare(b[1]));
    content.innerHTML = `<div class="page">${heading("Canonical identities", "All rated clubs", "Search every club that survived validation and played at least one rated match. Historical and inactive clubs remain available even when they are not eligible for the current ranking.")}<section class="panel"><div class="controls"><div class="field grow"><label for="club-search">Club, association or code</label><input id="club-search" type="search" placeholder="Start typing"></div><div class="field"><label for="club-country">Association</label><select id="club-country"><option value="">All associations</option>${countries.map(([value, label]) => `<option value="${escapeHTML(value)}">${escapeHTML(label)}</option>`).join("")}</select></div><div class="field"><label for="club-status">Status</label><select id="club-status"><option value="">All clubs</option><option value="active">Current ranking only</option><option value="inactive">Historical / inactive</option></select></div></div><div id="club-table"></div></section></div>`;
    const search = document.getElementById("club-search");
    const country = document.getElementById("club-country");
    const status = document.getElementById("club-status");
    const target = document.getElementById("club-table");
    function render() {
      const query = search.value.trim().toLocaleLowerCase();
      const rows = clubs.filter((club) => (!query || `${club.name} ${club.country_name} ${club.code}`.toLocaleLowerCase().includes(query)) && (!country.value || club.country === country.value) && (!status.value || (status.value === "active") === club.active));
      const visible = rows.slice(0, 750);
      target.innerHTML = `<div class="result-note">Showing ${number(visible.length)} of ${number(rows.length)} matching clubs from ${number(clubs.length)} rated identities.</div><div class="table-wrap"><table><thead><tr><th>Club</th><th>Association</th><th class="numeric">Latest rating</th><th class="numeric">Matches</th><th>Coverage</th><th>Status</th></tr></thead><tbody>${visible.map((club) => `<tr><td>${clubLink(club.code, club.name)}<span class="subline">${escapeHTML(club.code)}</span></td><td>${escapeHTML(club.country_name)}<span class="subline">${escapeHTML(club.continent)}</span></td><td class="numeric rating">${rating(club.rating)}</td><td class="numeric">${number(club.matches)}</td><td>${escapeHTML(club.first)} – ${escapeHTML(club.last)}</td><td><span class="badge${club.active ? " cross" : ""}">${club.active ? "Current" : "Historical"}</span>${club.provisional ? `<span class="subline">Under 30 matches</span>` : ""}</td></tr>`).join("")}</tbody></table></div>`;
    }
    search.addEventListener("input", render);
    [country, status].forEach((control) => control.addEventListener("change", render));
    render();
  }

  async function clubPage(code) {
    loading("Loading club history…");
    await getClubs();
    const payload = await getJSON(`club/${encodeURIComponent(code)}.json`);
    const club = payload.club;
    const annual = payload.annual;
    const latestYear = payload.match_years.at(-1)?.[0];
    document.title = `${club.name} · Global Club Rankings`;
    content.innerHTML = `<div class="page">${heading(club.country_name || "Club profile", escapeHTML(club.name), `${escapeHTML(club.country_name)} · ${escapeHTML(club.continent)} · results from ${escapeHTML(club.first)} through ${escapeHTML(club.last)}`, `<p class="as-of"><strong>${club.active ? `#${club.rank}` : "Inactive"}</strong>${club.active ? "current global rank" : "outside activity window"}</p>`)}<section class="club-summary"><article class="panel identity-card"><p class="eyebrow">Uncertainty-adjusted public rating</p><div class="rating-hero"><strong>${rating(club.rating)}</strong><span>Mean ${rating(club.mean)}<br>Standard error ±${number(club.se, 1)}</span></div><p class="lede">${club.provisional ? "Provisional: fewer than 30 rated appearances." : "Established rating with at least 30 rated appearances."}</p></article><dl class="panel detail-list"><div><dt>Association</dt><dd>${escapeHTML(club.country_name)}</dd></div><div><dt>Latest tier</dt><dd>${club.tier}</dd></div><div><dt>Rated matches</dt><dd>${number(club.matches)}</dd></div><div><dt>Coverage</dt><dd>${escapeHTML(club.first)} – ${escapeHTML(club.last)}</dd></div><div><dt>Canonical code</dt><dd>${escapeHTML(club.code)}</dd></div><div><dt>Identity rule</dt><dd>${escapeHTML(club.resolution)}</dd></div></dl></section><section class="panel"><div class="panel-head"><div><h2>Annual rating trajectory</h2><p>Frozen state at the opening of each year; current rating is shown above.</p></div></div>${lineChart([{ name: club.name, points: annual.map((row) => [row[0], row[1]]) }], { label: `${club.name} annual ratings` })}</section><section class="panel"><div class="panel-head"><div><h2>Complete match history</h2><p>Select any season year in the archive. Source references, pre-match probabilities and aggregate weights remain attached.</p></div></div><div class="controls"><div class="field"><label for="club-match-year">Calendar year</label><select id="club-match-year">${[...payload.match_years].reverse().map((row) => `<option value="${row[0]}"${row[0] === latestYear ? " selected" : ""}>${row[0]} · ${number(row[1])} matches</option>`).join("")}</select></div></div><div id="club-matches"><div class="empty">Choose a year.</div></div></section></div>`;
    const year = document.getElementById("club-match-year");
    const target = document.getElementById("club-matches");
    async function loadMatches() {
      if (!year.value) { target.innerHTML = `<div class="empty">No match years are available.</div>`; return; }
      target.innerHTML = `<div class="empty">Loading ${escapeHTML(year.value)}…</div>`;
      const rows = (await getJSON(`matches/${year.value}.json`)).matches
        .map(matchObject)
        .filter((match) => match.home === code || match.away === code)
        .reverse();
      target.innerHTML = matchRows(rows, 1000);
    }
    year?.addEventListener("change", loadMatches);
    await loadMatches();
  }

  async function matchesPage() {
    loading("Loading match archive index…");
    const [index] = await Promise.all([getJSON("matches/index.json"), getClubs()]);
    const latest = index.years.at(-1)?.year;
    content.innerHTML = `<div class="page">${heading("Every retained source row", "Competitive match archive", "Browse the complete canonical ledger by calendar year. All probabilities are genuinely pre-match; all same-date fixtures share one frozen start-of-day state.")}<section class="panel"><div class="controls"><div class="field"><label for="match-year">Calendar year</label><select id="match-year">${[...index.years].reverse().map((row) => `<option value="${row.year}"${row.year === latest ? " selected" : ""}>${row.year} · ${number(row.count)}</option>`).join("")}</select></div><div class="field grow"><label for="match-search">Club or competition</label><input id="match-search" type="search" placeholder="Search this year"></div><div class="field"><label for="match-kind">Competition type</label><select id="match-kind"><option value="">All types</option><option value="league">League</option><option value="state">State</option><option value="domestic_cup">Domestic cup</option><option value="playoff">Playoff</option><option value="continental">Continental</option><option value="intercontinental">Intercontinental</option><option value="global">Global</option><option value="super_cup">Super cup</option></select></div></div><div id="match-table"></div></section></div>`;
    const year = document.getElementById("match-year");
    const search = document.getElementById("match-search");
    const kind = document.getElementById("match-kind");
    const target = document.getElementById("match-table");
    let rows = [];
    async function loadYear() {
      target.innerHTML = `<div class="empty">Loading ${escapeHTML(year.value)}…</div>`;
      rows = (await getJSON(`matches/${year.value}.json`)).matches.map(matchObject).reverse();
      render();
    }
    function render() {
      const query = search.value.trim().toLocaleLowerCase();
      const filtered = rows.filter((match) => (!kind.value || match.kind === kind.value) && (!query || `${clubName(match.home)} ${clubName(match.away)} ${match.competition}`.toLocaleLowerCase().includes(query)));
      target.innerHTML = matchRows(filtered);
    }
    year.addEventListener("change", loadYear);
    search.addEventListener("input", render);
    kind.addEventListener("change", render);
    await loadYear();
  }

  async function recordsPage() {
    loading("Loading club records…");
    const [records] = await Promise.all([getJSON("records.json"), getClubs()]);
    content.innerHTML = `<div class="page">${heading("Replay-derived records", "Peaks, upsets and defining matches", "Records are match instances from the same published replay, not a separate ranking. Use the tabs to inspect rating peaks, strongest pairings, surprises, aggregate-aware legs and annual number ones.")}<section class="panel"><div class="controls"><div class="tab-row" id="record-tabs"><button type="button" data-record="peaks" aria-pressed="true">Club peaks</button><button type="button" data-record="strongest" aria-pressed="false">Strongest matches</button><button type="button" data-record="upsets" aria-pressed="false">Largest upsets</button><button type="button" data-record="aggregate" aria-pressed="false">Aggregate cases</button><button type="button" data-record="leaders" aria-pressed="false">Yearly #1</button></div></div><div id="record-body"></div></section></div>`;
    const target = document.getElementById("record-body");
    function render(name) {
      if (name === "peaks") {
        target.innerHTML = `<div class="table-wrap"><table><thead><tr><th class="rank">Rank</th><th>Club</th><th>Association</th><th class="numeric">Peak rating</th><th>Date reached</th></tr></thead><tbody>${records.peaks.map((row, index) => `<tr><td class="rank">${index + 1}</td><td>${clubLink(row.club, row.name)}</td><td>${escapeHTML(row.country)}</td><td class="numeric rating">${rating(row.rating)}</td><td>${escapeHTML(row.date)}</td></tr>`).join("")}</tbody></table></div>`;
      } else if (name === "leaders") {
        target.innerHTML = `<div class="table-wrap"><table><thead><tr><th>Opening year</th><th>World #1</th><th class="numeric">Rating</th></tr></thead><tbody>${[...records.year_opening_number_ones].reverse().map((row) => `<tr><td>${row.year}</td><td>${clubLink(row.club, row.name)}</td><td class="numeric rating">${rating(row.rating)}</td></tr>`).join("")}</tbody></table></div>`;
      } else {
        const key = name === "strongest" ? "strongest_matches" : (name === "upsets" ? "upsets" : "aggregate_examples");
        target.innerHTML = matchRows(records[key].map(matchObject), 250);
      }
    }
    document.getElementById("record-tabs").addEventListener("click", (event) => {
      const button = event.target.closest("[data-record]");
      if (!button) return;
      document.querySelectorAll("[data-record]").forEach((item) => item.setAttribute("aria-pressed", String(item === button)));
      render(button.dataset.record);
    });
    render("peaks");
  }

  function clubSelectOptions(clubs, selected) {
    return selectOptions(clubs, selected, "code", (club) => `${club.name} — ${club.country_name}`);
  }

  async function comparePage() {
    loading("Loading comparison catalog…");
    const [rankings] = await Promise.all([getJSON("rankings.json"), getClubs()]);
    const choices = [...clubCatalog].sort((a, b) => a.name.localeCompare(b.name));
    const first = rankings.clubs[0]?.code;
    const second = rankings.clubs[1]?.code;
    content.innerHTML = `<div class="page">${heading("Shared annual scale", "Compare two clubs", "Compare the published annual rating trajectory and latest state of any two rated clubs, including inactive historical identities.")}<section class="panel"><div class="controls"><div class="field grow"><label for="compare-a">First club</label><select id="compare-a">${clubSelectOptions(choices, first)}</select></div><div class="field grow"><label for="compare-b">Second club</label><select id="compare-b">${clubSelectOptions(choices, second)}</select></div><button class="button" id="compare-run" type="button">Compare</button></div><div id="compare-result"></div></section></div>`;
    const a = document.getElementById("compare-a");
    const b = document.getElementById("compare-b");
    const target = document.getElementById("compare-result");
    async function compare() {
      target.innerHTML = `<div class="empty">Loading both histories…</div>`;
      const [one, two] = await Promise.all([
        getJSON(`club/${encodeURIComponent(a.value)}.json`),
        getJSON(`club/${encodeURIComponent(b.value)}.json`),
      ]);
      target.innerHTML = `<div class="panel-body"><div class="compare-grid"><article class="predict-team"><span>${escapeHTML(one.club.country_name)}</span><strong>${clubLink(one.club.code, one.club.name)}</strong><span>Rating ${rating(one.club.rating)} · mean ${rating(one.club.mean)}</span></article><div class="versus">VS</div><article class="predict-team"><span>${escapeHTML(two.club.country_name)}</span><strong>${clubLink(two.club.code, two.club.name)}</strong><span>Rating ${rating(two.club.rating)} · mean ${rating(two.club.mean)}</span></article></div></div>${lineChart([{ name: one.club.name, points: one.annual.map((row) => [row[0], row[1]]) }, { name: two.club.name, points: two.annual.map((row) => [row[0], row[1]]) }], { label: `${one.club.name} and ${two.club.name} annual ratings` })}`;
    }
    document.getElementById("compare-run").addEventListener("click", compare);
    await compare();
  }

  function logistic10(difference) {
    return 1 / (1 + 10 ** (-Math.max(-4800, Math.min(4800, difference)) / 400));
  }

  function threeWay(difference, drawPeak) {
    const expected = logistic10(difference);
    const draw = drawPeak * 4 * expected * (1 - expected);
    const home = Math.max(1e-12, expected - .5 * draw);
    const away = Math.max(1e-12, 1 - expected - .5 * draw);
    const total = home + draw + away;
    return [home / total, draw / total, away / total];
  }

  async function predictPage() {
    loading("Loading current predictor state…");
    const rankings = await getJSON("rankings.json");
    const parameters = (await getJSON("meta.json")).parameters;
    const clubs = rankings.clubs;
    content.innerHTML = `<div class="page">${heading("Current-state calculator", "Predict a club match", "This calculator uses the same current latent means, fitted draw curve and separate domestic/cross-border home advantages as the replay. Ratings remain the cautious ranking output.")}<section class="panel"><div class="controls"><div class="field grow"><label for="predict-home">First-listed club</label><select id="predict-home">${clubSelectOptions(clubs, clubs[0]?.code)}</select></div><div class="field"><label for="predict-venue">Venue</label><select id="predict-venue"><option value="home">First club at home</option><option value="neutral">Neutral</option><option value="away">Second club at home</option></select></div><div class="field grow"><label for="predict-away">Second-listed club</label><select id="predict-away">${clubSelectOptions(clubs, clubs[1]?.code)}</select></div></div><div class="panel-body" id="prediction"></div></section><p class="notice">The calculator is a transparent model view, not a fixture feed or betting recommendation. It does not invent an aggregate state for a future leg.</p></div>`;
    const home = document.getElementById("predict-home");
    const away = document.getElementById("predict-away");
    const venue = document.getElementById("predict-venue");
    const target = document.getElementById("prediction");
    const byCode = new Map(clubs.map((club) => [club.code, club]));
    function render() {
      const one = byCode.get(home.value);
      const two = byCode.get(away.value);
      if (!one || !two || one.code === two.code) { target.innerHTML = `<div class="empty">Choose two different clubs.</div>`; return; }
      const cross = one.country !== two.country;
      const advantage = venue.value === "neutral" ? 0 : Number(parameters[cross ? "home_advantage_cross_border" : "home_advantage_domestic"]) * (venue.value === "home" ? 1 : -1);
      const difference = Number(one.mean) - Number(two.mean) + advantage;
      const probabilities = threeWay(difference, Number(parameters.draw_peak));
      target.innerHTML = `<div class="predict-grid"><article class="predict-team"><span>${escapeHTML(one.country_name)}</span><strong>${escapeHTML(one.name)}</strong><span>Rating ${rating(one.rating)} · mean ${rating(one.mean)}</span></article><div class="versus">VS</div><article class="predict-team"><span>${escapeHTML(two.country_name)}</span><strong>${escapeHTML(two.name)}</strong><span>Rating ${rating(two.rating)} · mean ${rating(two.mean)}</span></article></div><div class="prediction-result"><div><strong>${percent(probabilities[0])}</strong><span>${escapeHTML(one.name)} win</span></div><div><strong>${percent(probabilities[1])}</strong><span>Draw</span></div><div><strong>${percent(probabilities[2])}</strong><span>${escapeHTML(two.name)} win</span></div></div><p class="notice">Mean difference ${signed(Number(one.mean) - Number(two.mean), 1)}; ${cross ? "cross-border" : "domestic"} venue adjustment ${signed(advantage, 1)}; forecast difference ${signed(difference, 1)}.</p>`;
    }
    [home, away, venue].forEach((control) => control.addEventListener("change", render));
    render();
  }

  async function methodologyPage() {
    loading("Loading the frozen club methodology…");
    const meta = await getJSON("meta.json");
    const p = meta.parameters;
    const fit = meta.fit || {};
    const exampleWeight = Number(p.aggregate_floor) + (1 - Number(p.aggregate_floor)) * Math.exp(-3 / Number(p.aggregate_scale));
    content.innerHTML = `<div class="page">${heading("Separate from the national-team model", "Club rating methodology", "A scalable hierarchical Elo replay connects domestic club strength through association coefficients learned from cross-border competition. Its parameters and validation are frozen independently.")}<article class="panel prose"><h2>Published rating and global connection</h2><p>Each club has a residual and each domestic association has a coefficient. Domestic results update the two club residuals. Cross-border results divide their update between the clubs and their associations, making leagues comparable without pretending every club plays in one competition.</p><div class="formula">mean = ${rating(p.base_rating)} + club residual + association coefficient
rating = mean − ${number(p.uncertainty_penalty, 2)} × standard error

forecast difference = home mean − away mean + venue adjustment</div><p>The ranking uses the lower, uncertainty-adjusted rating. Forecasts use the latent mean. This prevents sparse or inward-looking data from appearing as certain as a heavily connected club.</p><h2>Home, away and neutral</h2><p>The fitted domestic home adjustment is <strong>${signed(p.home_advantage_domestic, 0)} points</strong>; the cross-border home adjustment is <strong>${signed(p.home_advantage_cross_border, 0)} points</strong>. Neutral matches receive zero. Swapping the two clubs and reversing the venue swaps the win probabilities exactly.</p><h2>Two-leg ties and aggregate intent</h2><p>A second leg keeps full weight when the aggregate is level, the leader also wins the leg, or the leg produces a comeback. Only a loss by the club that remains ahead on aggregate is discounted. The retained information is:</p><div class="formula">weight = floor + (1 − floor) × max(exp(−|before| / scale), exp(−|after| / scale))
floor = ${p.aggregate_floor}; scale = ${p.aggregate_scale} goals</div><p>For the user’s example—4–0 in the first leg, then a controlled 0–1 loss—the second leg is worth about <strong>${number(exampleWeight * 100, 1)}%</strong> of an ordinary leg. The aggregate still records 4–1 superiority; the second result is not erased.</p><h2>Chronology and match treatment</h2><ul><li>Every forecast is stored before its result is learned.</li><li>All matches on one date use the same frozen start-of-day state, making same-date input order irrelevant.</li><li>Goal margin has a logarithmic multiplier; a huge score cannot create a linear runaway update.</li><li>Penalty shootouts are modelled as match draws and receive a reduced information weight.</li><li>Season regression pulls a club toward its current tier prior; association coefficients regress more slowly.</li></ul><h2>Frozen coefficients</h2><div class="table-wrap"><table><thead><tr><th>Coefficient</th><th class="numeric">Value</th><th>Role</th></tr></thead><tbody><tr><td>K factor</td><td class="numeric">${p.k_factor}</td><td>Base result update</td></tr><tr><td>Draw peak</td><td class="numeric">${p.draw_peak}</td><td>Maximum draw probability at even strength</td></tr><tr><td>Margin scale</td><td class="numeric">${p.margin_scale}</td><td>Logarithmic goal-margin response</td></tr><tr><td>Season retention</td><td class="numeric">${p.season_retention}</td><td>Year-to-year club carryover</td></tr><tr><td>Club share</td><td class="numeric">${p.association_share}</td><td>Cross-border update allocated to club residuals</td></tr><tr><td>Tier gap</td><td class="numeric">${p.tier_gap}</td><td>Prior points per tier below the first</td></tr><tr><td>Club prior SD</td><td class="numeric">${p.club_prior_sd}</td><td>Initial club uncertainty</td></tr><tr><td>Association prior SD</td><td class="numeric">${p.association_prior_sd}</td><td>Initial association uncertainty</td></tr></tbody></table></div><h2>Chronological validation</h2><p>${escapeHTML(fit.status || "Frozen after chronological validation")}. The selection replay warms up from ${escapeHTML(fit.replay_from || "2000-01-01")}, selects on ${escapeHTML((fit.validation_period || []).join(" to "))}, and reports an untouched test window of ${escapeHTML((fit.test_period || []).join(" to "))}.</p>${fit.all_match_log_loss ? metricCards([{ label: "Validation matches", value: number(fit.validation_matches), note: `log loss ${number(fit.all_match_log_loss.validation, 4)}` }, { label: "Test matches", value: number(fit.test_matches), note: `log loss ${number(fit.all_match_log_loss.test, 4)}` }, { label: "Aggregate follow-up test", value: number(fit.controlled_tie_followup_log_loss?.test_matches || 0), note: `${number(fit.controlled_tie_followup_log_loss?.ordinary_test, 6)} → ${number(fit.controlled_tie_followup_log_loss?.aggregate_aware_test, 6)}` }, { label: "Full replay", value: number(meta.matches), note: `log loss ${number(meta.model_metrics?.all?.log_loss, 4)}` }]) : ""}<h2>Interpretation</h2><p>These numbers are comparative estimates, not claims that every match ever played has been recovered. Source corrections, added competitions and better identity evidence can change future replays while the coefficients remain frozen.</p></article></div>`;
  }

  async function sourcesPage() {
    loading("Loading source provenance…");
    const [sources, competitions] = await Promise.all([getJSON("sources.json"), getJSON("competitions.json")]);
    const groups = new Map();
    for (const source of sources.runtime.sources) {
      const family = source.key.split(":")[0];
      if (!groups.has(family)) groups.set(family, { ...source, files: 0, bytes: 0 });
      const group = groups.get(family);
      group.files += 1;
      group.bytes += source.bytes;
    }
    content.innerHTML = `<div class="page">${heading("Audited provenance", "Sources, coverage and limitations", "The supplied research directory guided discovery. The unattended replay uses machine-readable feeds that can be schema-checked, attributed, hash-recorded and traced to individual rows.")}<article class="panel prose"><h2>Discovery index</h2><p><a href="${escapeHTML(sources.discovery_index.url)}" rel="external">${escapeHTML(sources.discovery_index.name)}</a> — ${escapeHTML(sources.discovery_index.role)}</p><h2>Runtime source blend</h2><div class="source-grid">${[...groups.values()].map((group) => `<section class="source-card"><h3>${escapeHTML(group.attribution)}</h3><p>${number(group.files)} file${group.files === 1 ? "" : "s"} · ${number(group.bytes / 1_000_000, 1)} MB downloaded · ${escapeHTML(group.licence)}</p><p><a href="${escapeHTML(group.url)}" rel="external">Source endpoint</a></p></section>`).join("")}${sources.brazil ? `<section class="source-card"><h3>${escapeHTML(sources.brazil.attribution)}</h3><p>${number(sources.brazil.matches)} compacted matches · ${escapeHTML(sources.brazil.first)} to ${escapeHTML(sources.brazil.last)} · ${escapeHTML(sources.brazil.licence)}</p><p><a href="${escapeHTML(sources.brazil.source_url)}" rel="external">BrazilianFootball/Data</a></p></section>` : ""}${sources.brazil_states ? `<section class="source-card"><h3>${escapeHTML(sources.brazil_states.attribution)}</h3><p>${number(sources.brazil_states.matches)} state matches across ${number(sources.brazil_states.competitions)} championships · ${escapeHTML(sources.brazil_states.first)} to ${escapeHTML(sources.brazil_states.last)} · ${escapeHTML(sources.brazil_states.licence)}</p><p><a href="${escapeHTML(sources.brazil_states.source_url)}" rel="external">FerrerasRP/FootballData</a></p></section>` : ""}</div><h2>Retained match coverage</h2><div class="table-wrap"><table><thead><tr><th>Source</th><th class="numeric">Matches</th><th>First</th><th>Last</th><th class="numeric">Competitions</th></tr></thead><tbody>${sources.coverage.map((row) => `<tr><td>${escapeHTML(row.source)}</td><td class="numeric">${number(row.matches)}</td><td>${escapeHTML(row.first)}</td><td>${escapeHTML(row.last)}</td><td class="numeric">${number(row.competitions)}</td></tr>`).join("")}</tbody></table></div><h2>Competition catalog</h2><p>The generated catalog currently contains ${number(competitions.competitions.length)} distinct source/jurisdiction competition keys. Different countries’ top divisions remain distinct even when their raw labels are blank or overloaded.</p><div class="table-wrap"><table><thead><tr><th>Competition</th><th>Type</th><th class="numeric">Matches</th><th>Coverage</th><th>Source</th></tr></thead><tbody>${competitions.competitions.slice(0, 250).map((row) => `<tr><td>${escapeHTML(row.name)}</td><td>${escapeHTML(slugLabel(row.kind))}</td><td class="numeric">${number(row.matches)}</td><td>${escapeHTML(row.first)} – ${escapeHTML(row.last)}</td><td>${escapeHTML(row.sources.join(", "))}</td></tr>`).join("")}</tbody></table></div><h2>Known limitations</h2><ul>${sources.limitations.map((item) => `<li>${escapeHTML(item)}</li>`).join("")}</ul><h2>Additional corroboration</h2><ul>${sources.additional_research.map((item) => `<li><a href="${escapeHTML(item.url)}" rel="external">${escapeHTML(item.name)}</a> — ${escapeHTML(item.role)}</li>`).join("")}</ul></article></div>`;
  }

  function parseRoute() {
    const raw = decodeURIComponent(location.hash.replace(/^#\/?/, ""));
    const parts = raw.split("/").filter(Boolean);
    return { name: parts[0] || "rankings", value: parts[1] || "" };
  }

  function updateNav(name) {
    const parent = name === "club" ? "clubs" : name;
    document.querySelectorAll(".site-nav a[href^='#/']").forEach((link) => {
      const current = link.getAttribute("href") === `#/${parent}`;
      if (current) link.setAttribute("aria-current", "page");
      else link.removeAttribute("aria-current");
    });
  }

  async function route(force = false) {
    if (force) cache.clear();
    const current = parseRoute();
    updateNav(current.name);
    document.title = "Global Club Rankings · Network Football Elo";
    try {
      if (!bootstrap || force) bootstrap = await getJSON("bootstrap.json");
      const handlers = {
        rankings: rankingsPage,
        history: historyPage,
        clubs: clubsPage,
        club: () => clubPage(current.value),
        matches: matchesPage,
        records: recordsPage,
        compare: comparePage,
        predict: predictPage,
        methodology: methodologyPage,
        sources: sourcesPage,
      };
      if (!handlers[current.name] || (current.name === "club" && !current.value)) {
        location.hash = "#/rankings";
        return;
      }
      await handlers[current.name]();
      document.querySelector(".site-nav")?.classList.remove("is-open");
      document.querySelector(".menu-button")?.setAttribute("aria-expanded", "false");
      content.focus({ preventScroll: true });
      window.scrollTo({ top: 0, behavior: "instant" });
    } catch (error) {
      fail(error);
    }
  }

  const toggle = document.querySelector(".menu-button");
  toggle?.addEventListener("click", () => {
    const nav = document.getElementById("site-nav");
    const open = nav.classList.toggle("is-open");
    toggle.setAttribute("aria-expanded", String(open));
  });
  window.addEventListener("hashchange", () => route());
  route();
})();
