(() => {
  "use strict";

  window.__nfeloBoot = window.__nfeloBoot || {};
  window.__nfeloBoot.started = true;

  const DATA = "data/";
  const content = document.getElementById("content");
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
  let matchArchiveFiles = null;

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
    if (!Number.isFinite(numeric)) return "—";
    return `${numeric > 0 ? "+" : ""}${number(numeric, digits)}`;
  };
  const slugLabel = (value) => String(value || "")
    .replaceAll("_", " ")
    .replaceAll("-", " ")
    .replace(/\b\w/g, (letter) => letter.toUpperCase());

  const validDate = (value) => {
    if (!/^\d{4}-\d{2}-\d{2}$/.test(String(value || ""))) return escapeHTML(value || "—");
    const [year, month, day] = String(value).split("-").map(Number);
    return new Intl.DateTimeFormat("en-GB", {
      day: "numeric",
      month: "long",
      year: "numeric",
      timeZone: "UTC",
    }).format(new Date(Date.UTC(year, month - 1, day)));
  };

  const validTimestamp = (value) => {
    const parsed = new Date(value);
    if (Number.isNaN(parsed.valueOf())) return escapeHTML(value || "—");
    return new Intl.DateTimeFormat("en-GB", {
      day: "numeric",
      month: "long",
      year: "numeric",
      hour: "2-digit",
      minute: "2-digit",
      timeZone: "UTC",
      timeZoneName: "short",
    }).format(parsed);
  };

  async function getJSON(path) {
    if (!cache.has(path)) {
      cache.set(path, fetch(`${DATA}${path}`).then(async (response) => {
        if (!response.ok) throw new Error(`${path} returned HTTP ${response.status}`);
        if (!path.endsWith(".gz")) return response.json();
        const bytes = new Uint8Array(await response.arrayBuffer());
        if (bytes[0] !== 0x1f || bytes[1] !== 0x8b) {
          return JSON.parse(new TextDecoder().decode(bytes));
        }
        if (typeof DecompressionStream !== "function") {
          throw new Error("This browser cannot open the compressed match archive.");
        }
        const stream = new Blob([bytes]).stream()
          .pipeThrough(new DecompressionStream("gzip"));
        return new Response(stream).json();
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

  async function getMatchYear(year) {
    if (!matchArchiveFiles) {
      const index = await getJSON("matches/index.json");
      matchArchiveFiles = new Map(index.years.map((row) => [String(row.year), row.file]));
    }
    return getJSON(`matches/${matchArchiveFiles.get(String(year)) || `${year}.json.gz`}`);
  }

  function matchObject(row) {
    return Object.fromEntries(MATCH_FIELDS.map((field, index) => [field, row[index]]));
  }

  function setTitle(title = "") {
    document.title = title
      ? `${title} · Global Club Rankings · Network Football Elo`
      : "Global Club Rankings · Network Football Elo";
  }

  function loading(label = "Loading club data…") {
    content.innerHTML = `<div class="loading-shell" role="status"><span class="spinner" aria-hidden="true"></span><p>${escapeHTML(label)}</p></div>`;
  }

  function fail(error) {
    console.error(error);
    window.__nfeloBoot.failed = true;
    content.innerHTML = `
      <div class="error-panel" role="alert">
        <p class="eyebrow">Build data unavailable</p>
        <h2>The club ratings could not be loaded.</h2>
        <p>${escapeHTML(error?.message || error)}</p>
        <button class="button button-dark" type="button" id="retry-route">Retry</button>
      </div>`;
    document.getElementById("retry-route")?.addEventListener("click", () => route(true));
  }

  function pageHeading(eyebrow, title, lede, salon = false) {
    return `
      <header class="page-heading${salon ? " page-heading-salon" : ""}">
        <div><p class="eyebrow">${escapeHTML(eyebrow)}</p><h1>${escapeHTML(title)}</h1></div>
        <p class="lede">${lede}</p>
      </header>`;
  }

  function clubFor(value) {
    return typeof value === "string" ? clubMap?.get(value) : value;
  }

  function clubLink(code, name) {
    return `<a class="team-link" href="#/club/${encodeURIComponent(code)}">${escapeHTML(name)}</a>`;
  }

  function clubIdentity(value, { link = true, compact = false } = {}) {
    const club = clubFor(value) || {
      code: typeof value === "string" ? value : "",
      name: typeof value === "string" ? value : "Unknown club",
      country_name: "",
      continent: "",
    };
    const name = link ? clubLink(club.code, club.name) : escapeHTML(club.name);
    const context = [club.country_name, club.continent].filter(Boolean).join(" · ");
    return `<span class="club-identity${compact ? " club-identity-compact" : ""}"><span class="club-name">${name}</span><span class="club-context">${escapeHTML(context)}</span></span>`;
  }

  function selectionOptions(items, selected, includeRank = false) {
    return items.map((club) => `<option value="${escapeHTML(club.code)}"${club.code === selected ? " selected" : ""}>${includeRank && club.rank ? `No. ${club.rank} · ` : ""}${escapeHTML(club.name)} · ${escapeHTML(club.country_name)}</option>`).join("");
  }

  function paginationHTML(shown, total, prefix) {
    if (shown >= total) return `<div class="pagination"><span class="muted small">Showing all ${number(total)}</span></div>`;
    return `
      <div class="pagination">
        <span class="muted small" aria-live="polite">Showing ${number(shown)} of ${number(total)}</span>
        <div class="pagination-actions">
          <button class="button" type="button" id="${prefix}-more">Show more</button>
          <button class="button button-quiet" type="button" id="${prefix}-all">Show all</button>
        </div>
      </div>`;
  }

  function clubRankingTable(items, { useStoredRank = true, prefix = "ranking" } = {}) {
    if (!items.length) return `<div class="empty"><h2>No matching clubs</h2><p>Try a broader search or another filter.</p></div>`;
    const rowRank = (club, index) => useStoredRank ? (club.rank ?? index + 1) : index + 1;
    return `
      <div class="ranking-desktop">
        <div class="table-shell">
          <table class="ranking-table club-ranking-table">
            <thead><tr>
              <th class="numeric">Rank</th><th>Club</th><th class="numeric">Rating</th>
              <th class="numeric">Underlying strength estimate</th>
              <th class="numeric hide-mobile">Uncertainty</th>
              <th class="numeric hide-mobile">Matches</th>
              <th>Latest tier / result</th>
            </tr></thead>
            <tbody>${items.map((club, index) => `<tr>
              <td class="rank-cell numeric">${rowRank(club, index)}</td>
              <td>${clubIdentity(club)}</td>
              <td class="numeric"><span class="rating-main">${rating(club.rating)}</span><span class="rating-sub">uncertainty ${rating(club.se)}</span></td>
              <td class="numeric">${rating(club.mean)}</td>
              <td class="numeric hide-mobile">±${rating(club.se)}</td>
              <td class="numeric hide-mobile">${number(club.matches)}</td>
              <td><span class="club-tier">Tier ${number(club.tier)}</span><span class="rating-sub">${validDate(club.last)}</span></td>
            </tr>`).join("")}</tbody>
          </table>
        </div>
      </div>
      <ol class="ranking-cards" aria-label="Club rankings">
        ${items.map((club, index) => `<li class="ranking-card">
          <div class="ranking-card-heading">
            <span class="ranking-card-rank">No. ${rowRank(club, index)}</span>
            <div class="ranking-card-rating"><strong>${rating(club.rating)}</strong><small>uncertainty ${rating(club.se)}</small></div>
          </div>
          <div class="ranking-card-team">${clubIdentity(club)}</div>
          <div class="ranking-card-snapshot">
            <div><span>Underlying strength</span><b>${rating(club.mean)}</b></div>
            <div><span>Latest tier</span><b>Tier ${number(club.tier)}</b></div>
          </div>
          <details class="ranking-card-details">
            <summary>More ranking details</summary>
            <dl>
              <div><dt>Matches</dt><dd>${number(club.matches)}</dd></div>
              <div><dt>Latest result</dt><dd>${validDate(club.last)}</dd></div>
              <div><dt>Status</dt><dd>${club.active ? "Current" : "Historical"}${club.provisional ? " · provisional" : ""}</dd></div>
            </dl>
          </details>
        </li>`).join("")}
      </ol>`;
  }

  function associationRankingTable(items) {
    return `
      <div class="ranking-desktop"><div class="table-shell"><table class="ranking-table">
        <thead><tr><th class="numeric">Rank</th><th>Nation</th><th class="numeric">Global coefficient</th><th class="numeric">Index</th><th class="numeric">Uncertainty</th><th class="numeric">Cross-border updates</th></tr></thead>
        <tbody>${items.map((row) => `<tr>
          <td class="rank-cell numeric">${row.rank}</td>
          <td><span class="club-identity"><span class="club-name">${escapeHTML(row.name)}</span><span class="club-context">${escapeHTML(row.continent)}</span></span></td>
          <td class="numeric"><span class="rating-main">${signed(row.coefficient, 1)}</span></td>
          <td class="numeric">${rating(row.index)}</td>
          <td class="numeric">±${rating(row.se)}</td>
          <td class="numeric">${number(row.cross_border_updates)}</td>
        </tr>`).join("")}</tbody>
      </table></div></div>
      <ol class="ranking-cards" aria-label="Association rankings">
        ${items.map((row) => `<li class="ranking-card">
          <div class="ranking-card-heading"><span class="ranking-card-rank">No. ${row.rank}</span><div class="ranking-card-rating"><strong>${signed(row.coefficient, 1)}</strong><small>global coefficient</small></div></div>
          <div class="ranking-card-team"><span class="club-identity"><span class="club-name">${escapeHTML(row.name)}</span><span class="club-context">${escapeHTML(row.continent)}</span></span></div>
          <div class="ranking-card-snapshot"><div><span>Index</span><b>${rating(row.index)}</b></div><div><span>Uncertainty</span><b>±${rating(row.se)}</b></div></div>
          <details class="ranking-card-details"><summary>More ranking details</summary><dl><div><dt>Cross-border updates</dt><dd>${number(row.cross_border_updates)}</dd></div></dl></details>
        </li>`).join("")}
      </ol>`;
  }

  function probabilityMarkup(match) {
    const values = [
      Math.max(0, Number(match.home_probability)),
      Math.max(0, Number(match.draw_probability)),
      Math.max(0, Number(match.away_probability)),
    ];
    return `<div class="club-probabilities" aria-label="Pre-match probabilities"><span>H <b>${percent(values[0])}</b></span><span>D <b>${percent(values[1])}</b></span><span>A <b>${percent(values[2])}</b></span></div>`;
  }

  function matchTableHTML(rows) {
    if (!rows.length) return `<div class="empty"><h2>No matching matches</h2><p>Try another year or broader filters.</p></div>`;
    return `
      <div class="table-hint" aria-hidden="true">Swipe horizontally to see every column →</div>
      <div class="table-shell club-match-table"><table>
        <thead><tr><th>Date</th><th>Match</th><th>Competition</th><th class="numeric">Ratings before → after</th><th>Pre-match W/D/L</th><th class="hide-mobile">Context / source</th></tr></thead>
        <tbody>${rows.map((match) => {
          const aggregate = Number(match.leg) === 2 && match.aggregate_before_home !== null;
          const status = match.status === "P" ? " · decided on penalties" : match.status === "E" ? " · extra time" : "";
          const context = [
            match.neutral ? "Neutral" : "Home venue",
            match.cross_border ? "cross-border" : "domestic",
            aggregate ? `leg 2 · ${number(Number(match.aggregate_weight) * 100, 0)}% information` : "",
          ].filter(Boolean).join(" · ");
          return `<tr>
            <td data-label="Date">${validDate(match.date)}</td>
            <td data-label="Match"><div class="club-match-pair"><span>${clubIdentity(match.home, { compact: true })}</span><strong class="score">${escapeHTML(match.home_goals)}–${escapeHTML(match.away_goals)}</strong><span>${clubIdentity(match.away, { compact: true })}</span></div></td>
            <td data-label="Competition">${escapeHTML(match.competition)}<span class="rating-sub">${escapeHTML(slugLabel(match.kind))}${escapeHTML(status)}</span></td>
            <td class="numeric" data-label="Ratings"><span class="rating-pair"><b>Home</b> ${rating(match.pre_home_rating)} → ${rating(match.post_home_rating)}</span><span class="rating-pair"><b>Away</b> ${rating(match.pre_away_rating)} → ${rating(match.post_away_rating)}</span></td>
            <td data-label="Probabilities">${probabilityMarkup(match)}</td>
            <td class="hide-mobile" data-label="Context">${escapeHTML(context)}<span class="rating-sub" title="${escapeHTML(match.source_ref)}">${escapeHTML(match.source)} · ${escapeHTML(match.round || match.source_ref)}</span></td>
          </tr>`;
        }).join("")}</tbody>
      </table></div>`;
  }

  function renderPagedMatches(target, rows, initial = 100) {
    let shown = Math.min(initial, rows.length);
    const draw = () => {
      target.innerHTML = matchTableHTML(rows.slice(0, shown)) + paginationHTML(shown, rows.length, `matches-${target.id || "table"}`);
      document.getElementById(`matches-${target.id || "table"}-more`)?.addEventListener("click", () => {
        shown = Math.min(rows.length, shown + initial);
        draw();
      });
      document.getElementById(`matches-${target.id || "table"}-all`)?.addEventListener("click", () => {
        shown = rows.length;
        draw();
      });
    };
    draw();
  }

  function lineChart(series, label) {
    const points = series.flatMap((item) => item.points)
      .filter((point) => Number.isFinite(Number(point[0])) && Number.isFinite(Number(point[1])));
    if (points.length < 2) return `<div class="empty"><h3>Not enough rating history</h3></div>`;
    const width = 920;
    const height = 320;
    const margin = { left: 58, right: 20, top: 20, bottom: 38 };
    let minX = Math.min(...points.map((point) => Number(point[0])));
    let maxX = Math.max(...points.map((point) => Number(point[0])));
    let minY = Math.min(...points.map((point) => Number(point[1])));
    let maxY = Math.max(...points.map((point) => Number(point[1])));
    if (minX === maxX) maxX += 1;
    const padding = Math.max(30, (maxY - minY) * 0.12);
    minY = Math.floor((minY - padding) / 50) * 50;
    maxY = Math.ceil((maxY + padding) / 50) * 50;
    const x = (value) => margin.left + ((value - minX) / (maxX - minX)) * (width - margin.left - margin.right);
    const y = (value) => margin.top + ((maxY - value) / (maxY - minY)) * (height - margin.top - margin.bottom);
    const grid = Array.from({ length: 5 }, (_, index) => {
      const value = minY + ((maxY - minY) * index) / 4;
      return `<line x1="${margin.left}" x2="${width - margin.right}" y1="${y(value)}" y2="${y(value)}"></line><text x="${margin.left - 9}" y="${y(value) + 4}" text-anchor="end">${Math.round(value)}</text>`;
    }).join("");
    const years = [...new Set([minX, Math.round((minX + maxX) / 2), maxX])]
      .map((value) => `<text x="${x(value)}" y="${height - 10}" text-anchor="middle">${value}</text>`).join("");
    const paths = series.map((item, index) => {
      const ordered = [...item.points].sort((a, b) => a[0] - b[0]);
      const d = ordered.map((point, pointIndex) => `${pointIndex ? "L" : "M"}${x(point[0]).toFixed(1)},${y(point[1]).toFixed(1)}`).join(" ");
      return `<path class="club-chart-series club-chart-series-${index + 1}" d="${d}"></path>`;
    }).join("");
    return `<div class="club-chart-wrap"><svg class="club-chart" viewBox="0 0 ${width} ${height}" role="img" aria-label="${escapeHTML(label)}"><g class="club-chart-grid">${grid}</g><g class="club-chart-years">${years}</g>${paths}</svg>${series.length > 1 ? `<div class="club-chart-legend">${series.map((item, index) => `<span class="club-chart-key-${index + 1}">${escapeHTML(item.name)}</span>`).join("")}</div>` : ""}</div>`;
  }

  async function homePage() {
    setTitle();
    loading("Loading the latest club ratings…");
    const [records] = await Promise.all([getJSON("records.json"), getClubs()]);
    const topTen = bootstrap.top.slice(0, 10);
    const strongest = records.strongest_matches.slice(0, 5).map(matchObject);
    content.innerHTML = `
      <div class="page home-page">
        <section class="home-intro">
          <div class="home-intro-copy">
            <p class="eyebrow">A global club rating, rebuilt from 1871</p>
            <h1>Club football, ranked in context.</h1>
            <p class="lede">Competitive results connect domestic leagues, lower tiers, cups and international competitions through club, nation and confederation strength.</p>
            <div class="hero-actions">
              <a class="button button-primary home-action home-action-rankings" href="#/rankings">See the rankings</a>
              <a class="button home-action home-action-fixtures" href="#/matches">Browse matches</a>
              <a class="button home-action home-action-predict" href="#/predict">Predict a matchup</a>
            </div>
          </div>
          <dl class="home-facts">
            <div><dt>Latest result</dt><dd>${validDate(bootstrap.meta.results_through)}</dd></div>
            <div><dt>Matches</dt><dd>${number(bootstrap.meta.matches)}</dd></div>
            <div><dt>Clubs</dt><dd>${number(bootstrap.meta.rated_clubs)}</dd></div>
            <div class="home-accuracy"><dt>Associations</dt><dd>${number(bootstrap.meta.associations)}</dd></div>
          </dl>
        </section>
        <section class="home-dashboard">
          <div class="home-ranking-list">
            <div class="compact-heading"><div><p class="eyebrow">Current rankings</p><h2>Top ten</h2></div><a href="#/rankings">Full rankings →</a></div>
            <ol>${topTen.map((club, index) => `<li><span class="home-rank">${index + 1}</span><span class="home-club-identity">${clubIdentity(club)}</span><strong>${rating(club.rating)}</strong><small>±${rating(club.se)}</small></li>`).join("")}</ol>
          </div>
          <aside class="home-upcoming">
            <div class="compact-heading"><div><p class="eyebrow">Latest archive</p><h2>Results through</h2></div><a href="#/matches">All matches →</a></div>
            <p class="club-home-date">${validDate(bootstrap.meta.results_through)}</p>
            <p class="muted">The static archive contains only completed, validated competitive matches. Use the match calculator for an arbitrary current pairing.</p>
            <a class="button button-dark" href="#/predict">Open match calculator →</a>
          </aside>
        </section>
        <section class="home-support">
          <div>
            <p class="eyebrow">What makes it different</p><h2>Club, nation and confederation all matter.</h2>
            <p>A club remains the main unit. Cross-border evidence also estimates domestic-association and confederation strength, allowing disconnected league systems to share one cautious scale.</p>
            <div class="home-help-links"><a href="#/methodology?section=strength">How the hierarchy works →</a><a href="#/faq">Questions? Read the FAQ →</a></div>
          </div>
          <div class="home-records">
            <div class="compact-heading"><div><p class="eyebrow">Record book</p><h2>Highest-rated matches</h2></div><a href="#/records">All records →</a></div>
            <ol>${strongest.map((match, index) => `<li><span class="home-record-rank">${index + 1}</span><div class="home-record-match"><span class="home-record-teams">${clubLink(match.home, clubFor(match.home)?.name || match.home)} <i>v</i> ${clubLink(match.away, clubFor(match.away)?.name || match.away)}</span><time datetime="${match.date}">${validDate(match.date)}</time></div><strong><small>Combined</small><span>${rating(Number(match.pre_home_rating) + Number(match.pre_away_rating))}</span></strong></li>`).join("")}</ol>
          </div>
        </section>
        <nav class="home-explore" aria-labelledby="home-explore-title">
          <div class="compact-heading"><div><p class="eyebrow">More ways to explore</p><h2 id="home-explore-title">Explore</h2></div></div>
          <div class="home-explore-links">
            <a href="#/history"><b>Historical rankings</b><span>Choose any year-opening snapshot.</span></a>
            <a href="#/tournaments"><b>Tournaments</b><span>Inspect every retained competition family and its coverage.</span></a>
            <a href="#/records"><b>Records</b><span>Peaks, number ones, matches, upsets and aggregate cases.</span></a>
            <a href="#/compare"><b>Compare clubs</b><span>Latest states and rating histories on one scale.</span></a>
          </div>
        </nav>
      </div>`;
  }

  async function rankingsPage() {
    setTitle("Rankings");
    loading("Loading global club rankings…");
    const [rankings, associations, allClubs] = await Promise.all([
      getJSON("rankings.json"),
      getJSON("associations.json"),
      getClubs(),
    ]);
    content.innerHTML = `
      <div class="page">
        ${pageHeading("Current senior men’s clubs", "Rankings", `The published rating combines estimated playing strength with an allowance for uncertainty. Club names remain the primary label; nation and confederation are shown beneath them. <a href="#/history">Choose a historical year →</a>`)}
        <div class="toolbar">
          <div class="field field-grow"><label for="ranking-search">Find a club or nation</label><input id="ranking-search" type="search" placeholder="Club, nation or confederation…"></div>
          <div class="field"><label for="ranking-sort">Sort</label><select id="ranking-sort"><option value="rating">Rating</option><option value="matches">Matches played</option><option value="name">Name</option><option value="country">Nation</option></select></div>
          <div class="toggle-group" role="group" aria-label="Ranking pool">
            <button class="button" data-pool="current" aria-pressed="true">Current clubs</button>
            <button class="button" data-pool="all" aria-pressed="false">All clubs, including historical</button>
            <button class="button" data-pool="associations" aria-pressed="false">Nations</button>
          </div>
        </div>
        <div class="record-note"><strong>Rating</strong><div><b>One cautious rating is used throughout the club section.</b> Forecasts use the underlying mean, while the ranking subtracts an uncertainty allowance. Nation and confederation coefficients connect otherwise separate domestic systems.</div></div>
        <div id="rankings-table"></div>
      </div>`;
    const search = document.getElementById("ranking-search");
    const sort = document.getElementById("ranking-sort");
    const target = document.getElementById("rankings-table");
    let pool = "current";
    let shown = 250;
    const draw = () => {
      const query = search.value.trim().toLocaleLowerCase();
      if (pool === "associations") {
        const rows = associations.associations.filter((row) => !query || `${row.name} ${row.continent}`.toLocaleLowerCase().includes(query));
        target.innerHTML = `<p class="muted small club-list-count">${number(rows.length)} matching nations</p>` + associationRankingTable(rows);
        return;
      }
      const source = pool === "all" ? allClubs : rankings.clubs;
      const rows = source.filter((club) => !query || `${club.name} ${club.country_name} ${club.continent}`.toLocaleLowerCase().includes(query));
      rows.sort((a, b) => {
        if (sort.value === "name") return a.name.localeCompare(b.name);
        if (sort.value === "country") return a.country_name.localeCompare(b.country_name) || a.name.localeCompare(b.name);
        if (sort.value === "matches") return Number(b.matches) - Number(a.matches) || Number(b.rating) - Number(a.rating);
        return Number(b.rating) - Number(a.rating);
      });
      const visible = rows.slice(0, shown);
      target.innerHTML = clubRankingTable(visible, { useStoredRank: pool === "current" && sort.value === "rating" }) + paginationHTML(visible.length, rows.length, "rankings");
      document.getElementById("rankings-more")?.addEventListener("click", () => { shown += 250; draw(); });
      document.getElementById("rankings-all")?.addEventListener("click", () => { shown = rows.length; draw(); });
    };
    search.addEventListener("input", () => { shown = 250; draw(); });
    sort.addEventListener("change", () => { shown = 250; draw(); });
    document.querySelectorAll("[data-pool]").forEach((button) => button.addEventListener("click", () => {
      pool = button.dataset.pool;
      shown = 250;
      document.querySelectorAll("[data-pool]").forEach((item) => item.setAttribute("aria-pressed", String(item === button)));
      draw();
    }));
    draw();
  }

  async function historyPage() {
    setTitle("History");
    loading("Loading historical rankings…");
    const [index] = await Promise.all([getJSON("history/index.json"), getClubs()]);
    const latest = index.years.at(-1)?.year;
    content.innerHTML = `
      <div class="page">
        ${pageHeading("Year-opening snapshots", "Historical rankings", "Choose the opening of any year. Each table uses only results completed before that snapshot and the same cautious rating used everywhere else.")}
        <div class="toolbar history-toolbar">
          <div class="field"><label for="history-year">Opening of year</label><select id="history-year">${[...index.years].reverse().map((row) => `<option value="${row.year}"${row.year === latest ? " selected" : ""}>${row.year} · ${number(row.clubs)} clubs</option>`).join("")}</select></div>
          <div class="field field-grow"><label for="history-search">Find a club or nation</label><input id="history-search" type="search" placeholder="Club, nation or confederation…"></div>
        </div>
        <div class="record-note"><strong>Snapshot</strong><div><b>Each year is a frozen start-of-year state.</b> Club is the main label; nation and confederation remain directly beneath it in both table and card views.</div></div>
        <div id="history-table"></div>
      </div>`;
    const year = document.getElementById("history-year");
    const search = document.getElementById("history-search");
    const target = document.getElementById("history-table");
    let rows = [];
    let shown = 250;
    const draw = () => {
      const query = search.value.trim().toLocaleLowerCase();
      const clubs = rows.map((row) => {
        const metadata = clubMap.get(row[1]) || { code: row[1], name: row[1], country_name: "", continent: "" };
        return { ...metadata, rank: row[0], rating: row[2], mean: row[3], se: row[4], matches: row[5], tier: row[6], last: row[7] };
      }).filter((club) => !query || `${club.name} ${club.country_name} ${club.continent}`.toLocaleLowerCase().includes(query));
      const visible = clubs.slice(0, shown);
      target.innerHTML = clubRankingTable(visible) + paginationHTML(visible.length, clubs.length, "history");
      document.getElementById("history-more")?.addEventListener("click", () => { shown += 250; draw(); });
      document.getElementById("history-all")?.addEventListener("click", () => { shown = clubs.length; draw(); });
    };
    const load = async () => {
      target.innerHTML = `<div class="loading-shell compact-loading" role="status"><span class="spinner" aria-hidden="true"></span><p>Loading ${escapeHTML(year.value)}…</p></div>`;
      rows = (await getJSON(`history/${year.value}.json`)).rankings;
      shown = 250;
      draw();
    };
    year.addEventListener("change", load);
    search.addEventListener("input", () => { shown = 250; draw(); });
    await load();
  }

  async function tournamentsPage() {
    setTitle("Tournaments");
    loading("Loading competition coverage…");
    const payload = await getJSON("competitions.json");
    const kinds = [...new Set(payload.competitions.map((row) => row.kind))].sort();
    content.innerHTML = `
      <div class="page">
        ${pageHeading("Domestic · continental · global", "Tournaments", "Explore every retained competition key. Domestic leagues, state championships, cups, playoffs, continental competitions and global events all feed the same club model.")}
        <div class="toolbar">
          <div class="field field-grow"><label for="competition-search">Find a competition</label><input id="competition-search" type="search" placeholder="Name, source or jurisdiction…"></div>
          <div class="field"><label for="competition-kind">Competition type</label><select id="competition-kind"><option value="">All types</option>${kinds.map((kind) => `<option value="${escapeHTML(kind)}">${escapeHTML(slugLabel(kind))}</option>`).join("")}</select></div>
        </div>
        <div class="record-note"><strong>Coverage</strong><div><b>Competition rows describe the retained match ledger, not titles or trophies.</b> Distinct domestic systems remain separate even where raw source labels are incomplete or reused.</div></div>
        <div id="competition-table"></div>
      </div>`;
    const search = document.getElementById("competition-search");
    const kind = document.getElementById("competition-kind");
    const target = document.getElementById("competition-table");
    let shown = 150;
    const draw = () => {
      const query = search.value.trim().toLocaleLowerCase();
      const rows = payload.competitions.filter((row) => (!kind.value || row.kind === kind.value) && (!query || `${row.name} ${row.key} ${row.sources.join(" ")}`.toLocaleLowerCase().includes(query)));
      const visible = rows.slice(0, shown);
      target.innerHTML = `<div class="table-hint" aria-hidden="true">Swipe horizontally to see every column →</div><div class="table-shell"><table><thead><tr><th>Competition</th><th>Type</th><th class="numeric">Matches</th><th class="numeric">Clubs</th><th>Coverage</th><th>Sources</th></tr></thead><tbody>${visible.map((row) => `<tr><td><b>${escapeHTML(row.name)}</b><span class="rating-sub">${escapeHTML(row.key)}</span></td><td>${escapeHTML(slugLabel(row.kind))}</td><td class="numeric">${number(row.matches)}</td><td class="numeric">${number(row.club_sides)}</td><td>${validDate(row.first)} – ${validDate(row.last)}</td><td>${escapeHTML(row.sources.join(", "))}</td></tr>`).join("")}</tbody></table></div>` + paginationHTML(visible.length, rows.length, "competitions");
      document.getElementById("competitions-more")?.addEventListener("click", () => { shown += 150; draw(); });
      document.getElementById("competitions-all")?.addEventListener("click", () => { shown = rows.length; draw(); });
    };
    search.addEventListener("input", () => { shown = 150; draw(); });
    kind.addEventListener("change", () => { shown = 150; draw(); });
    draw();
  }

  async function matchesPage() {
    setTitle("Matches");
    loading("Loading the match archive…");
    const [index] = await Promise.all([getJSON("matches/index.json"), getClubs()]);
    matchArchiveFiles = new Map(index.years.map((row) => [String(row.year), row.file]));
    const latest = index.years.at(-1)?.year;
    content.innerHTML = `
      <div class="page">
        ${pageHeading("Every retained competitive result", "Matches", "Browse the canonical ledger by calendar year. Scores show football goals only; a shootout decision never gets mixed into the displayed score.")}
        <div class="toolbar">
          <div class="field"><label for="match-year">Calendar year</label><select id="match-year">${[...index.years].reverse().map((row) => `<option value="${row.year}"${row.year === latest ? " selected" : ""}>${row.year} · ${number(row.count)}</option>`).join("")}</select></div>
          <div class="field field-grow"><label for="match-search">Club or competition</label><input id="match-search" type="search" placeholder="Club, nation or competition…"></div>
          <div class="field"><label for="match-kind">Competition type</label><select id="match-kind"><option value="">All types</option><option value="league">League</option><option value="state">State</option><option value="domestic_cup">Domestic cup</option><option value="playoff">Playoff</option><option value="continental">Continental</option><option value="intercontinental">Intercontinental</option><option value="global">Global</option><option value="super_cup">Super cup</option></select></div>
        </div>
        <div class="record-note"><strong>Pre-match</strong><div><b>Ratings and probabilities are frozen before the listed match.</b> Same-date matches share one start-of-day state. A controlled second-leg loss may receive reduced information weight when the club still advances comfortably on aggregate.</div></div>
        <div id="match-table"></div>
      </div>`;
    const year = document.getElementById("match-year");
    const search = document.getElementById("match-search");
    const kind = document.getElementById("match-kind");
    const target = document.getElementById("match-table");
    let rows = [];
    const draw = () => {
      const query = search.value.trim().toLocaleLowerCase();
      const filtered = rows.filter((match) => (!kind.value || match.kind === kind.value) && (!query || `${clubFor(match.home)?.name} ${clubFor(match.away)?.name} ${clubFor(match.home)?.country_name} ${clubFor(match.away)?.country_name} ${match.competition}`.toLocaleLowerCase().includes(query)));
      renderPagedMatches(target, filtered, 100);
    };
    const load = async () => {
      target.innerHTML = `<div class="loading-shell compact-loading" role="status"><span class="spinner" aria-hidden="true"></span><p>Loading ${escapeHTML(year.value)}…</p></div>`;
      rows = (await getMatchYear(year.value)).matches.map(matchObject).reverse();
      draw();
    };
    year.addEventListener("change", load);
    search.addEventListener("input", draw);
    kind.addEventListener("change", draw);
    await load();
  }

  function fixturesPage() {
    setTitle("Upcoming matches");
    content.innerHTML = `
      <div class="page">
        ${pageHeading("Fixture status", "Upcoming matches", "The club installation currently publishes a validated results archive, not an unverified global fixture feed. This page is retained in the same location as the national section so the two interfaces remain consistent.")}
        <section class="section">
          <div class="empty"><h2>No connected fixture feed</h2><p>Use the current-state calculator to evaluate any two active clubs at a home, away or neutral venue.</p><a class="button button-dark" href="#/predict">Open match calculator →</a></div>
        </section>
      </div>`;
  }

  async function recordsPage() {
    setTitle("Records");
    loading("Loading club records…");
    const [records] = await Promise.all([getJSON("records.json"), getClubs()]);
    content.innerHTML = `
      <div class="page">
        ${pageHeading("Replay-derived record book", "Records", "Every record comes from the same post-match club replay used by rankings and profiles. Peaks are recorded after the match that produced them.")}
        <div class="record-tabs" role="tablist" aria-label="Record type">
          <button class="button button-dark" role="tab" data-record="peaks" aria-pressed="true" aria-selected="true">Club peaks</button>
          <button class="button" role="tab" data-record="strongest" aria-pressed="false" aria-selected="false">Highest-rated matches</button>
          <button class="button" role="tab" data-record="upsets" aria-pressed="false" aria-selected="false">Largest upsets</button>
          <button class="button" role="tab" data-record="aggregate" aria-pressed="false" aria-selected="false">Aggregate cases</button>
          <button class="button" role="tab" data-record="leaders" aria-pressed="false" aria-selected="false">No. 1 chronology</button>
        </div>
        <div id="record-table"></div>
      </div>`;
    const target = document.getElementById("record-table");
    const draw = (name) => {
      if (name === "peaks") {
        target.innerHTML = `<div class="table-shell"><table><thead><tr><th class="numeric">Rank</th><th>Club</th><th class="numeric">Post-match peak</th><th>Date reached</th></tr></thead><tbody>${records.peaks.map((row, index) => {
          const metadata = clubFor(row.club) || { code: row.club, name: row.name, country_name: row.country, continent: "" };
          return `<tr><td class="rank-cell numeric">${index + 1}</td><td>${clubIdentity(metadata)}</td><td class="numeric"><span class="rating-main">${rating(row.rating)}</span></td><td>${validDate(row.date)}</td></tr>`;
        }).join("")}</tbody></table></div>`;
      } else if (name === "leaders") {
        target.innerHTML = `<div class="table-shell"><table><thead><tr><th>Opening year</th><th>World no. 1</th><th class="numeric">Rating</th></tr></thead><tbody>${[...records.year_opening_number_ones].reverse().map((row) => `<tr><td>${row.year}</td><td>${clubIdentity(clubFor(row.club) || { code: row.club, name: row.name })}</td><td class="numeric"><span class="rating-main">${rating(row.rating)}</span></td></tr>`).join("")}</tbody></table></div>`;
      } else {
        const key = name === "strongest" ? "strongest_matches" : name === "upsets" ? "upsets" : "aggregate_examples";
        renderPagedMatches(target, records[key].map(matchObject), 100);
      }
    };
    document.querySelectorAll("[data-record]").forEach((button) => button.addEventListener("click", () => {
      document.querySelectorAll("[data-record]").forEach((item) => {
        const selected = item === button;
        item.setAttribute("aria-pressed", String(selected));
        item.setAttribute("aria-selected", String(selected));
        item.classList.toggle("button-dark", selected);
      });
      draw(button.dataset.record);
    }));
    draw("peaks");
  }

  async function comparePage() {
    setTitle("Compare");
    loading("Loading comparison data…");
    const [rankings] = await Promise.all([getJSON("rankings.json"), getClubs()]);
    const choices = [...clubCatalog].sort((a, b) => a.name.localeCompare(b.name));
    const first = rankings.clubs[0]?.code;
    const second = rankings.clubs[1]?.code;
    content.innerHTML = `
      <div class="page">
        ${pageHeading("Shared global scale", "Compare clubs", "Compare the latest state and annual rating trajectory of any two rated clubs, including historical and inactive identities.")}
        <section class="comparison-selection" aria-labelledby="comparison-selection-title">
          <div class="section-heading compact-heading"><div><p class="eyebrow">Two clubs</p><h2 id="comparison-selection-title">Clubs in this comparison</h2></div></div>
          <div class="predictor comparison-picker">
            <div class="team-picker"><label for="compare-a">First club</label><select id="compare-a">${selectionOptions(choices, first)}</select></div>
            <div class="versus" aria-hidden="true">v</div>
            <div class="team-picker"><label for="compare-b">Second club</label><select id="compare-b">${selectionOptions(choices, second)}</select></div>
          </div>
        </section>
        <div id="compare-result"></div>
      </div>`;
    const a = document.getElementById("compare-a");
    const b = document.getElementById("compare-b");
    const target = document.getElementById("compare-result");
    const draw = async () => {
      target.innerHTML = `<div class="loading-shell compact-loading" role="status"><span class="spinner" aria-hidden="true"></span><p>Loading both histories…</p></div>`;
      if (a.value === b.value) {
        target.innerHTML = `<div class="error-panel"><h2>Choose two different clubs</h2></div>`;
        return;
      }
      const [one, two] = await Promise.all([getJSON(`club/${a.value}.json`), getJSON(`club/${b.value}.json`)]);
      target.innerHTML = `
        <section class="section">
          <div class="section-heading"><div><p class="eyebrow">Latest published state</p><h2>Comparison summary</h2></div></div>
          <div class="table-shell"><table><thead><tr><th>Club</th><th class="numeric">Rating</th><th class="numeric">Underlying strength</th><th class="numeric">Uncertainty</th><th class="numeric">Matches</th><th>Coverage</th></tr></thead><tbody>
            ${[one.club, two.club].map((club) => `<tr><td>${clubIdentity(club)}</td><td class="numeric"><span class="rating-main">${rating(club.rating)}</span></td><td class="numeric">${rating(club.mean)}</td><td class="numeric">±${rating(club.se)}</td><td class="numeric">${number(club.matches)}</td><td>${validDate(club.first)} – ${validDate(club.last)}</td></tr>`).join("")}
          </tbody></table></div>
        </section>
        <section class="section"><div class="section-heading"><div><p class="eyebrow">Opening of each year</p><h2>Rating histories</h2></div></div>${lineChart([
          { name: one.club.name, points: one.annual.map((row) => [row[0], row[1]]) },
          { name: two.club.name, points: two.annual.map((row) => [row[0], row[1]]) },
        ], `${one.club.name} and ${two.club.name} annual ratings`)}</section>`;
    };
    [a, b].forEach((select) => select.addEventListener("change", draw));
    await draw();
  }

  function logistic10(difference) {
    return 1 / (1 + 10 ** (-Math.max(-4800, Math.min(4800, difference)) / 400));
  }

  function threeWay(difference, drawPeak) {
    const expected = logistic10(difference);
    const draw = drawPeak * 4 * expected * (1 - expected);
    const home = Math.max(1e-12, expected - 0.5 * draw);
    const away = Math.max(1e-12, 1 - expected - 0.5 * draw);
    const total = home + draw + away;
    return [home / total, draw / total, away / total];
  }

  async function predictPage() {
    setTitle("Predict a match");
    loading("Loading current predictor state…");
    const [rankings, meta] = await Promise.all([getJSON("rankings.json"), getJSON("meta.json")]);
    const clubs = rankings.clubs;
    const first = clubs[0]?.code;
    const second = clubs[1]?.code;
    content.innerHTML = `
      <div class="page predict-page">
        ${pageHeading("Current match calculator", "Predict a match", "Choose two active clubs and a venue. The forecast uses underlying club strength plus the relevant domestic or cross-border home adjustment; the displayed ranking remains the cautious rating.")}
        <div class="predictor" aria-label="Match pairing">
          <div class="team-picker"><p class="eyebrow">Club one</p><select id="predict-a" aria-label="Club one">${selectionOptions(clubs, first, true)}</select></div>
          <div class="versus" aria-hidden="true">v</div>
          <div class="team-picker"><p class="eyebrow">Club two</p><select id="predict-b" aria-label="Club two">${selectionOptions(clubs, second, true)}</select></div>
        </div>
        <div class="toolbar section predict-options"><div class="field"><label for="predict-venue">Venue</label><select id="predict-venue"><option value="neutral">Neutral</option><option value="home">Club one at home</option><option value="away">Club two at home</option></select></div></div>
        <div id="forecast"></div>
        <div class="record-note"><strong>Model view</strong><div><b>This is not a fixture feed or betting recommendation.</b> It does not invent an aggregate state for a future second leg and does not use line-ups, injuries, travel, rest or market prices.</div></div>
      </div>`;
    const a = document.getElementById("predict-a");
    const b = document.getElementById("predict-b");
    const venue = document.getElementById("predict-venue");
    const target = document.getElementById("forecast");
    const byCode = new Map(clubs.map((club) => [club.code, club]));
    const draw = () => {
      const one = byCode.get(a.value);
      const two = byCode.get(b.value);
      if (!one || !two || one.code === two.code) {
        target.innerHTML = `<div class="error-panel"><h2>Choose two different clubs</h2></div>`;
        return;
      }
      const crossBorder = one.country !== two.country;
      const baseAdvantage = Number(meta.parameters[crossBorder ? "home_advantage_cross_border" : "home_advantage_domestic"]);
      const advantage = venue.value === "neutral" ? 0 : baseAdvantage * (venue.value === "home" ? 1 : -1);
      const difference = Number(one.mean) - Number(two.mean) + advantage;
      const probabilities = threeWay(difference, Number(meta.parameters.draw_peak));
      const maximum = Math.max(...probabilities);
      const labels = [`${one.name} win`, "Draw", `${two.name} win`];
      target.innerHTML = `<section class="forecast" aria-live="polite"><div class="forecast-title"><div><p class="eyebrow">Current club forecast</p><h2>${escapeHTML(one.name)} v ${escapeHTML(two.name)}</h2></div><span>${venue.value === "neutral" ? "neutral venue" : venue.value === "home" ? `${escapeHTML(one.name)} home` : `${escapeHTML(two.name)} home`}</span></div><div class="forecast-bars">${probabilities.map((value, index) => `<div class="forecast-outcome${value === maximum ? " is-top" : ""}"><span>${escapeHTML(labels[index])}</span><strong>${percent(value)}</strong></div>`).join("")}</div><div class="forecast-meta"><span>${escapeHTML(one.name)} <b>No. ${one.rank} · ${rating(one.rating)}</b><small class="club-forecast-context">${escapeHTML(one.country_name)} · ${escapeHTML(one.continent)}</small></span><span>${escapeHTML(two.name)} <b>No. ${two.rank} · ${rating(two.rating)}</b><small class="club-forecast-context">${escapeHTML(two.country_name)} · ${escapeHTML(two.continent)}</small></span><span>Underlying difference <b>${signed(Number(one.mean) - Number(two.mean), 1)}</b></span><span>${crossBorder ? "Cross-border" : "Domestic"} venue adjustment <b>${signed(advantage, 1)}</b></span></div></section>`;
    };
    [a, b, venue].forEach((control) => control.addEventListener("change", draw));
    draw();
  }

  async function clubPage(code) {
    loading("Loading club history…");
    await getClubs();
    const payload = await getJSON(`club/${encodeURIComponent(code)}.json`);
    const club = payload.club;
    setTitle(club.name);
    const latestYear = payload.match_years.at(-1)?.[0];
    content.innerHTML = `
      <div class="page">
        <section class="team-hero">
          <div><p class="eyebrow">${escapeHTML(club.country_name)} · ${escapeHTML(club.continent)} · ${club.active ? `current world no. ${club.rank}` : "historical club record"}</p><h1>${escapeHTML(club.name)}</h1></div>
          <div class="team-rating"><strong>${rating(club.rating)}</strong><span>uncertainty ${rating(club.se)}</span></div>
        </section>
        <div class="team-stats">
          <div><span>Matches</span><strong>${number(club.matches)}</strong></div>
          <div><span>Nation</span><strong>${escapeHTML(club.country_name)}</strong></div>
          <div><span>Confederation</span><strong>${escapeHTML(club.continent)}</strong></div>
          <div><span>Latest tier</span><strong>${number(club.tier)}</strong></div>
          <div><span>Coverage</span><strong>${validDate(club.first)} – ${validDate(club.last)}</strong></div>
        </div>
        <nav class="context-actions team-context-actions" aria-label="Club tools"><a class="button button-quiet" href="#/compare">Compare this club</a><a class="button button-quiet" href="#/predict">Predict a matchup</a><a class="button button-quiet" href="#/rankings">Current rankings</a></nav>
        <section class="section"><div class="section-heading"><div><p class="eyebrow">Opening of each year</p><h2>Rating history</h2></div></div>${lineChart([{ name: club.name, points: payload.annual.map((row) => [row[0], row[1]]) }], `${club.name} annual ratings`)}</section>
        <section class="section"><div class="section-heading"><div><p class="eyebrow">Complete competitive record</p><h2>Matches</h2></div></div><div class="toolbar"><div class="field"><label for="club-match-year">Calendar year</label><select id="club-match-year">${[...payload.match_years].reverse().map((row) => `<option value="${row[0]}"${row[0] === latestYear ? " selected" : ""}>${row[0]} · ${number(row[1])} matches</option>`).join("")}</select></div></div><div id="club-matches"></div></section>
      </div>`;
    const year = document.getElementById("club-match-year");
    const target = document.getElementById("club-matches");
    const load = async () => {
      if (!year?.value) {
        target.innerHTML = `<div class="empty"><p>No match years are available.</p></div>`;
        return;
      }
      target.innerHTML = `<div class="loading-shell compact-loading" role="status"><span class="spinner" aria-hidden="true"></span><p>Loading ${escapeHTML(year.value)}…</p></div>`;
      const rows = (await getMatchYear(year.value)).matches.map(matchObject)
        .filter((match) => match.home === code || match.away === code).reverse();
      renderPagedMatches(target, rows, 100);
    };
    year?.addEventListener("change", load);
    await load();
  }

  async function methodologyPage(query = new URLSearchParams()) {
    setTitle("Methodology");
    loading("Loading club methodology…");
    const meta = await getJSON("meta.json");
    const p = meta.parameters;
    const fit = meta.fit || {};
    const exampleWeight = Number(p.aggregate_floor) + (1 - Number(p.aggregate_floor)) * Math.exp(-3 / Number(p.aggregate_scale));
    content.innerHTML = `
      <article class="page page-narrow prose methodology-page">
        ${pageHeading("Model · evidence · limitations", "Methodology", "The club section uses a separate hierarchical Elo replay. It keeps the national site’s presentation while adding club, nation, confederation, competition-tier and aggregate-tie evidence.", true)}
        <nav class="method-contents" aria-label="Methodology sections">
          <a href="#/methodology?section=overview">Plain-English overview</a><a href="#/methodology?section=strength">Connected strength</a><a href="#/methodology?section=venue">Home and away</a><a href="#/methodology?section=aggregate">Two-leg ties</a><a href="#/methodology?section=learning">Learning from results</a><a href="#/methodology?section=ratings">Published ratings</a><a href="#/methodology?section=validation">Release evidence</a><a href="#/methodology?section=limits">Limits and reproducibility</a>
        </nav>
        <section class="method-section" aria-labelledby="method-overview"><h2 id="method-overview" tabindex="-1">In plain English</h2><ol class="method-steps"><li><b>Keep the club primary.</b> Every match updates the two clubs first.</li><li><b>Connect domestic systems.</b> Cross-border matches also estimate nation and confederation coefficients.</li><li><b>Respect competition depth.</b> Tier priors and uncertainty prevent a lightly evidenced club from leaping the table.</li><li><b>Predict before learning.</b> Every stored probability is calculated before its result is applied.</li><li><b>Interpret a tie as a tie.</b> A controlled second-leg loss can carry less information when the club still wins comfortably on aggregate.</li><li><b>Publish one cautious rating.</b> Rankings subtract uncertainty from the underlying forecast mean.</li></ol></section>
        <section class="method-section" aria-labelledby="method-strength"><h2 id="method-strength" tabindex="-1">Club, nation and confederation strength</h2><p>Each club has its own residual. Its domestic association contributes a nation coefficient, while inter-confederation competition provides the global bridge.</p><div class="formula">mean = ${rating(p.base_rating)} + club residual + tier prior + nation coefficient + confederation bridge<br>forecast difference = home mean − away mean + venue adjustment</div><details class="method-details"><summary>Why the nation anchor uses elite associations</summary><p>Global club competitions select leading teams, not an average club from each association. Nation coefficients are therefore centred at the evidence-weighted ${number(Number(p.country_anchor_quantile) * 100, 0)}th percentile within each confederation, avoiding a regional boost merely because it contains many weak leagues.</p></details></section>
        <section class="method-section" aria-labelledby="method-venue"><h2 id="method-venue" tabindex="-1">Home, away and neutral</h2><p>Domestic home advantage is <b>${signed(p.home_advantage_domestic, 0)}</b> points. Cross-border home advantage is <b>${signed(p.home_advantage_cross_border, 0)}</b> points. Neutral and correctly identified global-tournament matches receive zero.</p><div class="formula">d = μhome − μaway + H<br>H = 0 at a neutral venue</div></section>
        <section class="method-section" aria-labelledby="method-aggregate"><h2 id="method-aggregate" tabindex="-1">Two-leg ties and aggregate intent</h2><p>A second leg keeps full weight when the tie is level, the leader confirms its advantage or the trailing club completes a comeback. Only a controlled loss by a club that remains ahead is discounted.</p><div class="formula">weight = floor + (1 − floor) × max(exp(−|before| / scale), exp(−|after| / scale))<br>floor = ${p.aggregate_floor}; scale = ${p.aggregate_scale} goals</div><p>A 4–0 first leg followed by a controlled 0–1 loss retains about <b>${number(exampleWeight * 100, 1)}%</b> of ordinary second-leg information, so the 4–1 aggregate better reflects the balance of the tie.</p></section>
        <section class="method-section" aria-labelledby="method-learning"><h2 id="method-learning" tabindex="-1">Learning from results</h2><p>Every forecast is stored before the result is learned. Goal margin has diminishing influence, extra-time and penalty decisions carry their declared evidence weights, and shootout kicks are removed from the football score.</p><details class="method-details"><summary>Competition and regional update shares</summary><p>Continental results assign ${number(Number(p.country_share) * 100, 0)}% of the cross-border structural update to association strength. Global inter-confederation results assign ${number(Number(p.confederation_share) * 100, 0)}% of the regional bridge update to confederation strength. The club retains the primary match-specific signal.</p></details></section>
        <section class="method-section" aria-labelledby="method-ratings"><h2 id="method-ratings" tabindex="-1">The published rating</h2><div class="formula">rating = mean − ${number(p.uncertainty_penalty, 2)} × standard error</div><p>The mean powers forecasts. The lower confidence-adjusted rating powers current and historical rankings, club pages and post-match peaks. Ratings are always displayed with one decimal place and no thousands separator.</p></section>
        <section class="method-section" aria-labelledby="method-validation"><h2 id="method-validation" tabindex="-1">Release coefficients and evidence</h2><div class="table-hint" aria-hidden="true">Swipe horizontally to see every column →</div><div class="table-shell parameter-table"><table><thead><tr><th>Coefficient</th><th class="numeric">Value</th><th>Role</th></tr></thead><tbody><tr><td>K factor</td><td class="numeric">${p.k_factor}</td><td>Base result update</td></tr><tr><td>Draw peak</td><td class="numeric">${p.draw_peak}</td><td>Maximum draw probability</td></tr><tr><td>Club retention</td><td class="numeric">${p.club_retention}</td><td>Year-to-year club carryover</td></tr><tr><td>Nation share</td><td class="numeric">${p.country_share}</td><td>Continental update assigned to nation coefficient</td></tr><tr><td>Confederation share</td><td class="numeric">${p.confederation_share}</td><td>Global update assigned to confederation bridge</td></tr><tr><td>Club prior SD</td><td class="numeric">${p.club_prior_sd}</td><td>Initial club uncertainty</td></tr></tbody></table></div><p><b>${escapeHTML(fit.status || "Chronological club replay")}.</b> ${escapeHTML(fit.selection || "")}</p><div class="record-note"><strong>Release</strong><div><b>${escapeHTML(meta.model_version)}</b><br>${number(meta.matches)} retained matches through ${validDate(meta.results_through)}; ${number(meta.active_clubs)} active clubs across ${number(meta.associations)} associations.</div></div></section>
        <section class="method-section" aria-labelledby="method-limits"><h2 id="method-limits" tabindex="-1">Reproducibility and limits</h2><p>The installer rebuilds a temporary ledger, model database and static archive, validates them, then replaces the published version as a whole. A failed refresh leaves the previous site intact.</p><p>The model does not know line-ups, injuries, red cards, tactics, travel, rest, weather or betting markets. Historical identity resolution and incomplete competition coverage remain modelling limits.</p></section>
      </article>`;
    const requested = query.get("section");
    if (["overview", "strength", "venue", "aggregate", "learning", "ratings", "validation", "limits"].includes(requested)) {
      requestAnimationFrame(() => document.getElementById(`method-${requested}`)?.scrollIntoView({ block: "start" }));
    }
  }

  function faqItems() {
    return [
      ["What is the club rating?", "It is a cautious estimate of a club’s strength on the latest retained date. The underlying mean is used for forecasts; the public rating subtracts an uncertainty allowance and is used everywhere else."],
      ["Why are nation and confederation shown beneath each club?", "The club is always the primary identity. Nation and confederation provide the smaller geographic context and also identify the two structural coefficient levels that connect domestic competitions globally."],
      ["How can clubs from different continents be compared?", "Competitive cross-border matches estimate association strength within confederations, while inter-confederation and global competitions bridge those regional scales. Uncertainty remains larger where evidence is thin."],
      ["Why can a lower-rated club be favoured in a forecast?", "The ranking is deliberately cautious and includes an uncertainty deduction. A forecast uses the fuller underlying mean plus venue, so it can favour a club whose displayed rating is slightly lower."],
      ["How are two-leg ties handled?", "The first leg is learned normally. In the second leg, a controlled defeat by a club that still advances comfortably can receive less information weight, while a level tie, comeback or confirmed advantage keeps full weight."],
      ["Are penalty shootout kicks included in the score?", "No. The displayed football score contains regulation and declared extra-time goals only. A penalty shootout is recorded as the deciding status and learned as a reduced-weight draw, never added to the scoreline."],
      ["Are peaks measured before or after a match?", "After the match. A peak is the published post-match rating produced by the result on the date shown."],
      ["Which matches are included?", "Only validated competitive senior men’s club matches retained from the configured domestic, state, cup, playoff, continental, intercontinental and global sources. Friendlies are excluded from this release."],
      ["Why might a club or result be missing?", "Global historical club data are incomplete and source labels can conflict. The pipeline fails closed when a score, identity or competition cannot be resolved safely, so uncertain rows do not overwrite the last verified site."],
      ["What should I report as a data correction?", "Send the two clubs, date, football score, competition, venue and a reliable supporting source through the project’s GitHub repository."],
    ];
  }

  function faqPage() {
    setTitle("Frequently asked questions");
    content.innerHTML = `
      <article class="page page-narrow prose faq-page">
        ${pageHeading("Understanding the club section", "Frequently asked questions", "Straightforward answers about global club ratings, regional coefficients, aggregate ties, penalties, records, coverage and updates.", true)}
        <div class="faq-tools" role="search"><div class="field field-grow"><label for="faq-search">Search questions</label><input id="faq-search" type="search" placeholder="Ratings, continents, penalties…" autocomplete="off"></div><div class="faq-actions" aria-label="Question controls"><button class="button" type="button" id="faq-expand">Expand all</button><button class="button button-quiet" type="button" id="faq-collapse">Collapse all</button></div></div>
        <p id="faq-count" class="muted small" aria-live="polite"></p><div id="faq-list" class="faq-list"></div>
        <div class="callout faq-more"><b>Looking for the exact calculations?</b> Start with <a href="#/methodology?section=strength">the club, nation and confederation hierarchy</a>, or open the full Methodology page.</div>
      </article>`;
    const items = faqItems();
    const search = document.getElementById("faq-search");
    const list = document.getElementById("faq-list");
    const count = document.getElementById("faq-count");
    const draw = () => {
      const query = search.value.trim().toLocaleLowerCase();
      const rows = items.filter(([question, answer]) => !query || `${question} ${answer}`.toLocaleLowerCase().includes(query));
      list.innerHTML = rows.length ? rows.map(([question, answer], index) => `<details class="faq-item"${!query && index === 0 ? " open" : ""}><summary>${escapeHTML(question)}</summary><div class="faq-answer"><p>${escapeHTML(answer)}</p></div></details>`).join("") : `<div class="empty-state"><h2>No matching questions</h2><p>Try a broader term or clear the search.</p></div>`;
      count.textContent = query ? `${rows.length} of ${items.length} questions shown` : `${items.length} questions`;
    };
    search.addEventListener("input", draw);
    document.getElementById("faq-expand").addEventListener("click", () => list.querySelectorAll("details").forEach((item) => { item.open = true; }));
    document.getElementById("faq-collapse").addEventListener("click", () => list.querySelectorAll("details").forEach((item) => { item.open = false; }));
    draw();
  }

  async function aboutPage() {
    setTitle("About");
    loading("Loading source and build information…");
    const [sources, competitions] = await Promise.all([getJSON("sources.json"), getJSON("competitions.json")]);
    const groups = new Map();
    for (const source of sources.runtime.sources) {
      const family = source.key.split(":")[0];
      if (!groups.has(family)) groups.set(family, { ...source, files: 0, bytes: 0 });
      const group = groups.get(family);
      group.files += 1;
      group.bytes += Number(source.bytes);
    }
    content.innerHTML = `
      <div class="page page-narrow prose about-page">
        ${pageHeading("Data · updates · limitations", "About", "Network Football Elo’s club section is an independent, results-only global strength and prediction system. Its model is separate from the national-team model, while its interface deliberately follows the national site.", true)}
        <section class="section split">
          <div class="panel"><p class="eyebrow">Results included through</p><h2>${validDate(bootstrap.meta.results_through)}</h2><p>${number(bootstrap.meta.matches)} matches across ${number(bootstrap.meta.rated_clubs)} club histories and ${number(bootstrap.meta.associations)} associations.</p><p class="muted small">Source data checked: ${validTimestamp(sources.runtime.retrieved_at)}<br>Site generated: ${validTimestamp(bootstrap.meta.generated_at)}</p></div>
          <div class="panel panel-dark"><p class="eyebrow">Update safety</p><h2>Built before it replaces anything.</h2><p class="muted">Each refresh creates and validates temporary databases and a complete temporary static archive. Only a successful build replaces the live club data; a failed update leaves the previous site unchanged.</p></div>
        </section>
        <article class="section prose">
          <h2>Data sources</h2><p>The discovery starting point was <a href="${escapeHTML(sources.discovery_index.url)}" rel="external">${escapeHTML(sources.discovery_index.name)}</a>. The unattended installation uses machine-readable sources that can be schema-checked, attributed and traced to individual rows.</p>
          <div class="table-hint" aria-hidden="true">Swipe horizontally to see every column →</div><div class="table-shell"><table><thead><tr><th>Source family</th><th class="numeric">Files</th><th class="numeric">Downloaded</th><th>Licence / terms</th><th>Endpoint</th></tr></thead><tbody>${[...groups.values()].map((group) => `<tr><td><b>${escapeHTML(group.attribution)}</b></td><td class="numeric">${number(group.files)}</td><td class="numeric">${number(group.bytes / 1_000_000, 1)} MB</td><td>${escapeHTML(group.licence)}</td><td><a href="${escapeHTML(group.url)}" rel="external">Source endpoint</a></td></tr>`).join("")}</tbody></table></div>
          <h2>Retained coverage</h2><div class="table-shell"><table><thead><tr><th>Source</th><th class="numeric">Matches</th><th>First</th><th>Last</th><th class="numeric">Competitions</th></tr></thead><tbody>${sources.coverage.map((row) => `<tr><td>${escapeHTML(row.source)}</td><td class="numeric">${number(row.matches)}</td><td>${validDate(row.first)}</td><td>${validDate(row.last)}</td><td class="numeric">${number(row.competitions)}</td></tr>`).join("")}</tbody></table></div>
          <h2>Competition scope</h2><p>The generated catalog currently contains ${number(competitions.competitions.length)} distinct competition keys. It spans domestic leagues and deep tiers, state championships, cups, playoffs, continental competitions and inter-confederation/global events.</p>
          <h2>Known limitations</h2><ul>${sources.limitations.map((item) => `<li>${escapeHTML(item)}</li>`).join("")}</ul>
          <h2>Quality checks</h2><p>Every update validates dates, scores, identities, duplicate handling, match order, probability sums, venue classification, confederation metadata, shootout-score normalisation, complete Club World Cup editions, post-match peaks and update-safe archive replacement.</p>
        </article>
      </div>`;
  }

  function parseRoute() {
    const raw = decodeURIComponent(location.hash.replace(/^#\/?/, ""));
    const [path, queryString = ""] = raw.split("?");
    const parts = path.split("/").filter(Boolean);
    return {
      name: parts[0] || "home",
      value: parts[1] || "",
      query: new URLSearchParams(queryString),
    };
  }

  function updateNavigation(name) {
    const active = name === "club" || name === "clubs" ? "rankings" : name;
    document.querySelectorAll(".site-nav a[href^='#/']").forEach((link) => {
      const section = link.getAttribute("href").replace(/^#\//, "").split("?")[0];
      if (section === active) link.setAttribute("aria-current", "page");
      else link.removeAttribute("aria-current");
    });
    document.querySelectorAll(".nav-group").forEach((group) => {
      const current = Boolean(group.querySelector("[aria-current='page']"));
      const summary = group.querySelector("summary");
      if (current) summary.setAttribute("aria-current", "page");
      else summary.removeAttribute("aria-current");
    });
  }

  function closeNavigation() {
    document.getElementById("site-nav")?.classList.remove("is-open");
    document.querySelector(".menu-button")?.setAttribute("aria-expanded", "false");
    document.querySelectorAll(".nav-group[open]").forEach((group) => { group.open = false; });
  }

  async function route(force = false) {
    if (force) {
      cache.clear();
      bootstrap = null;
      clubCatalog = null;
      clubMap = null;
      matchArchiveFiles = null;
      window.__nfeloBoot.failed = false;
    }
    const current = parseRoute();
    const aliases = { sources: "about", clubs: "rankings" };
    const name = aliases[current.name] || current.name;
    updateNavigation(name);
    document.body.dataset.route = name;
    document.body.dataset.pageFamily = ["methodology", "faq", "about"].includes(name) ? "salon" : "ledger";
    content.setAttribute("aria-busy", "true");
    try {
      if (!bootstrap) bootstrap = await getJSON("bootstrap.json");
      await (window.__nfeloStyleReady || Promise.resolve());
      const handlers = {
        home: homePage,
        rankings: rankingsPage,
        history: historyPage,
        tournaments: tournamentsPage,
        matches: matchesPage,
        fixtures: fixturesPage,
        records: recordsPage,
        compare: comparePage,
        predict: predictPage,
        club: () => current.value ? clubPage(current.value) : rankingsPage(),
        methodology: () => methodologyPage(current.query),
        faq: faqPage,
        about: aboutPage,
      };
      if (!handlers[name]) {
        content.innerHTML = `<div class="error-panel"><p class="eyebrow">404</p><h2>Page not found</h2><p>Return to a main section below.</p><div class="context-actions"><a class="button button-dark" href="#/rankings">Rankings</a><a class="button button-quiet" href="#/matches">Matches</a><a class="button button-quiet" href="#/">Home</a></div></div>`;
      } else {
        await handlers[name]();
      }
      content.setAttribute("aria-busy", "false");
      closeNavigation();
      window.__nfeloBoot.ready = true;
      content.focus({ preventScroll: true });
      window.scrollTo({ top: 0, behavior: "instant" });
    } catch (error) {
      content.setAttribute("aria-busy", "false");
      fail(error);
    }
  }

  const menuButton = document.querySelector(".menu-button");
  menuButton?.addEventListener("click", () => {
    const nav = document.getElementById("site-nav");
    const open = nav.classList.toggle("is-open");
    menuButton.setAttribute("aria-expanded", String(open));
  });
  document.querySelectorAll(".nav-group").forEach((group) => group.addEventListener("toggle", () => {
    if (!group.open) return;
    document.querySelectorAll(".nav-group[open]").forEach((other) => {
      if (other !== group) other.open = false;
    });
  }));
  document.addEventListener("click", (event) => {
    if (event.target.closest(".site-header")) return;
    closeNavigation();
  });
  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape") closeNavigation();
  });
  window.addEventListener("hashchange", () => route());
  route();
})();
