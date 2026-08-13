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

  const PAGE_FAMILIES = {
    home: "cover",
    club: "cover",
    methodology: "salon",
    faq: "salon",
    about: "salon",
  };

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

  function syncScrollableTableRegions() {
    document.querySelectorAll(".table-shell").forEach((shell) => {
      const table = shell.querySelector(":scope > table");
      if (!table) return;
      const active = shell.scrollWidth > shell.clientWidth + 2;
      const hint = shell.previousElementSibling?.matches(".table-hint")
        ? shell.previousElementSibling : null;
      if (hint) hint.hidden = !active;
      shell.toggleAttribute("data-nfelo-scroll-region", active);
      if (active) {
        shell.setAttribute("tabindex", "0");
        shell.setAttribute("role", "region");
        shell.setAttribute("aria-label", `${table.getAttribute("aria-label") || "Scrollable data table"}. Scroll horizontally for more columns.`);
      } else {
        shell.removeAttribute("tabindex");
        shell.removeAttribute("role");
        shell.removeAttribute("aria-label");
      }
    });
  }

  function syncScrollableFormulaRegions() {
    document.querySelectorAll(".methodology-page .formula").forEach((formula) => {
      const active = formula.scrollWidth > formula.clientWidth + 2;
      formula.toggleAttribute("data-nfelo-formula-overflow", active);
      if (active) {
        formula.setAttribute("tabindex", "0");
        formula.setAttribute("role", "region");
        formula.setAttribute("aria-label", "Scrollable formula. Scroll horizontally to see the full formula.");
      } else {
        formula.removeAttribute("tabindex");
        formula.removeAttribute("role");
        formula.removeAttribute("aria-label");
      }
    });
  }

  function syncHeadingRibbonGeometry() {
    if (typeof document.createRange !== "function") return;
    document.querySelectorAll(".page-heading h1").forEach((heading) => {
      heading.style.removeProperty("--nfelo-ribbon-inline");
      const headingRect = heading.getBoundingClientRect();
      if (headingRect.width < 1) return;
      const range = document.createRange();
      range.selectNodeContents(heading);
      const fragments = [...range.getClientRects()].filter((rect) => rect.width > 1 && rect.height > 1);
      range.detach?.();
      if (!fragments.length) return;
      const left = Math.min(...fragments.map((rect) => rect.left));
      const right = Math.max(...fragments.map((rect) => rect.right));
      const centre = Math.max(0, Math.min(headingRect.width, (left + right) / 2 - headingRect.left));
      heading.style.setProperty("--nfelo-ribbon-inline", `${centre.toFixed(2)}px`);
    });
  }

  function syncTabletRankingPresentation() {
    const desktop = document.querySelector('body[data-route="rankings"] .ranking-desktop');
    const cards = document.querySelector('body[data-route="rankings"] .ranking-cards');
    if (!desktop || !cards) return;
    const tablet = typeof window.matchMedia === "function"
      && window.matchMedia("(min-width: 901px) and (max-width: 1180px)").matches;
    desktop.toggleAttribute("hidden", tablet);
    cards.toggleAttribute("data-q8-tablet", tablet);
  }

  let responsiveFrame = 0;
  function syncResponsivePresentation() {
    cancelAnimationFrame(responsiveFrame);
    responsiveFrame = requestAnimationFrame(() => {
      syncScrollableTableRegions();
      syncScrollableFormulaRegions();
      syncHeadingRibbonGeometry();
      syncTabletRankingPresentation();
    });
  }

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

  function aggregateExplanation(match) {
    if (Number(match.leg) !== 2 || match.aggregate_before_home === null) return "";
    const margin = (value) => {
      const numeric = Number(value);
      if (numeric === 0) return "the tie was level";
      return `the home club ${numeric > 0 ? "led" : "trailed"} by ${Math.abs(numeric)}`;
    };
    return `Before this leg, ${margin(match.aggregate_before_home)}; afterwards, ${margin(match.aggregate_after_home)}. This result supplied ${number(Number(match.aggregate_weight) * 100, 1)}% of ordinary match information.`;
  }

  function matchStatus(match) {
    if (match.status === "P?") return "Decided on penalties · exact football score unavailable in the source";
    if (String(match.status).startsWith("P")) return "Decided on penalties";
    if (match.status === "E") return "After extra time";
    return "Full time";
  }

  function displayedScore(match) {
    return match.status === "P?"
      ? "Draw"
      : `${escapeHTML(match.home_goals)}–${escapeHTML(match.away_goals)}`;
  }

  function recordMetric(match, recordType) {
    if (recordType === "strongest") {
      return `<span class="record-metric"><b>${rating(Number(match.pre_home_rating) + Number(match.pre_away_rating))}</b> combined pre-match rating</span>`;
    }
    if (recordType === "upsets") {
      const observed = Number(match.home_goals) > Number(match.away_goals)
        ? Number(match.home_probability) : Number(match.away_probability);
      return `<span class="record-metric"><b>${percent(observed)}</b> winner probability · surprise ${number(match.surprise, 2)}</span>`;
    }
    if (recordType === "aggregate") {
      return `<span class="record-metric"><b>${number(Number(match.aggregate_weight) * 100, 1)}%</b> information weight</span>`;
    }
    return "";
  }

  function matchCardsHTML(rows, recordType = "") {
    return `<ol class="club-match-cards" aria-label="Matches">${rows.map((match) => {
      const aggregate = aggregateExplanation(match);
      const source = /^https?:\/\//.test(String(match.source_ref || ""))
        ? `<a href="${escapeHTML(match.source_ref)}" rel="external">Verified source</a>`
        : escapeHTML(match.source_ref || match.source);
      return `<li class="club-match-card">
        <header><time datetime="${escapeHTML(match.date)}">${validDate(match.date)}</time><span>${escapeHTML(match.competition)}</span></header>
        <div class="club-match-card-pair"><div>${clubIdentity(match.home)}</div><strong>${displayedScore(match)}</strong><div>${clubIdentity(match.away)}</div></div>
        <p class="club-match-status">${escapeHTML(matchStatus(match))} · ${escapeHTML(slugLabel(match.kind))}</p>
        ${recordMetric(match, recordType)}
        <dl class="club-match-card-data">
          <div><dt>Home rating</dt><dd>${rating(match.pre_home_rating)} → ${rating(match.post_home_rating)}</dd></div>
          <div><dt>Away rating</dt><dd>${rating(match.pre_away_rating)} → ${rating(match.post_away_rating)}</dd></div>
        </dl>
        ${probabilityMarkup(match)}
        ${aggregate ? `<div class="aggregate-note"><b>Aggregate context</b><p>${escapeHTML(aggregate)}</p></div>` : ""}
        <details><summary>Venue and provenance</summary><p>${match.neutral ? "Neutral venue" : "Home venue"} · ${match.cross_border ? "cross-border" : "domestic"}${match.round ? ` · ${escapeHTML(match.round)}` : ""}</p><p>${escapeHTML(match.source)} · ${source}</p></details>
      </li>`;
    }).join("")}</ol>`;
  }

  function matchTableHTML(rows, { recordType = "" } = {}) {
    if (!rows.length) return `<div class="empty"><h2>No matching matches</h2><p>Try another year or broader filters.</p></div>`;
    return `
      <div class="club-match-table-view">
      <div class="table-hint" aria-hidden="true">Swipe horizontally to see every column →</div>
      <div class="table-shell club-match-table"><table aria-label="Club match ledger">
        <thead><tr><th>Date</th><th>Match</th><th>Competition</th><th class="numeric">Ratings before → after</th><th>Pre-match W/D/L</th><th class="hide-mobile">Context / source</th></tr></thead>
        <tbody>${rows.map((match) => {
          const aggregate = Number(match.leg) === 2 && match.aggregate_before_home !== null;
          const context = [
            match.neutral ? "Neutral" : "Home venue",
            match.cross_border ? "cross-border" : "domestic",
            aggregate ? aggregateExplanation(match) : "",
          ].filter(Boolean).join(" · ");
          return `<tr>
            <td data-label="Date">${validDate(match.date)}</td>
            <td data-label="Match"><div class="club-match-pair"><span>${clubIdentity(match.home, { compact: true })}</span><strong class="score">${displayedScore(match)}</strong><span>${clubIdentity(match.away, { compact: true })}</span></div></td>
            <td data-label="Competition">${escapeHTML(match.competition)}<span class="rating-sub">${escapeHTML(slugLabel(match.kind))} · ${escapeHTML(matchStatus(match))}</span>${recordMetric(match, recordType)}</td>
            <td class="numeric" data-label="Ratings"><span class="rating-pair"><b>Home</b> ${rating(match.pre_home_rating)} → ${rating(match.post_home_rating)}</span><span class="rating-pair"><b>Away</b> ${rating(match.pre_away_rating)} → ${rating(match.post_away_rating)}</span></td>
            <td data-label="Probabilities">${probabilityMarkup(match)}</td>
            <td class="hide-mobile" data-label="Context">${escapeHTML(context)}<span class="rating-sub" title="${escapeHTML(match.source_ref)}">${escapeHTML(match.source)} · ${escapeHTML(match.round || match.source_ref)}</span></td>
          </tr>`;
        }).join("")}</tbody>
      </table></div></div>${matchCardsHTML(rows, recordType)}`;
  }

  function renderPagedMatches(target, rows, initial = 100, options = {}) {
    let shown = Math.min(initial, rows.length);
    const draw = () => {
      target.innerHTML = matchTableHTML(rows.slice(0, shown), options) + paginationHTML(shown, rows.length, `matches-${target.id || "table"}`);
      document.getElementById(`matches-${target.id || "table"}-more`)?.addEventListener("click", () => {
        shown = Math.min(rows.length, shown + initial);
        draw();
      });
      document.getElementById(`matches-${target.id || "table"}-all`)?.addEventListener("click", () => {
        shown = rows.length;
        draw();
      });
      syncResponsivePresentation();
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

  function recordDefinitionHTML(definition) {
    return `<article class="record-definition" aria-label="Record definition">
      <p class="eyebrow">Definition · order · safeguards</p>
      <h2>${escapeHTML(definition.title)}</h2>
      <dl>
        <div><dt>What is measured</dt><dd>${escapeHTML(definition.measure)}</dd></div>
        <div><dt>How it is ordered</dt><dd>${escapeHTML(definition.order)}</dd></div>
        <div><dt>Who is eligible</dt><dd>${escapeHTML(definition.eligibility)}</dd></div>
        <div><dt>How to read it</dt><dd>${escapeHTML(definition.interpretation)}</dd></div>
      </dl>
    </article>`;
  }

  function peakRecordsHTML(rows) {
    return `<div class="record-desktop"><div class="table-shell"><table aria-label="Post-match club peaks"><thead><tr><th class="numeric">Rank</th><th>Club</th><th class="numeric">Post-match peak</th><th>Match that produced it</th><th class="numeric">Underlying mean</th><th class="numeric">Uncertainty</th></tr></thead><tbody>${rows.map((row, index) => {
      const metadata = clubFor(row.club) || { code: row.club, name: row.name, country_name: row.country, continent: "" };
      const opponent = clubFor(row.opponent) || { code: row.opponent, name: row.opponent_name };
      return `<tr><td class="rank-cell numeric">${index + 1}</td><td>${clubIdentity(metadata)}</td><td class="numeric"><span class="rating-main">${rating(row.rating)}</span><span class="rating-sub">after ${number(row.matches_at_peak)} results</span></td><td>${validDate(row.date)}<span class="rating-sub">${escapeHTML(row.goals_for)}–${escapeHTML(row.goals_against)} v ${clubLink(opponent.code, opponent.name)} · ${escapeHTML(row.competition)}</span></td><td class="numeric">${rating(row.mean)}</td><td class="numeric">±${rating(row.se)}</td></tr>`;
    }).join("")}</tbody></table></div></div>
    <ol class="record-cards" aria-label="Post-match club peaks">${rows.map((row, index) => {
      const metadata = clubFor(row.club) || { code: row.club, name: row.name, country_name: row.country, continent: "" };
      const opponent = clubFor(row.opponent) || { code: row.opponent, name: row.opponent_name };
      return `<li class="record-card"><header><span>No. ${index + 1}</span><strong>${rating(row.rating)}</strong></header>${clubIdentity(metadata)}<dl><div><dt>Reached</dt><dd>${validDate(row.date)}</dd></div><div><dt>Producing result</dt><dd>${escapeHTML(row.goals_for)}–${escapeHTML(row.goals_against)} v ${clubLink(opponent.code, opponent.name)}</dd></div><div><dt>Competition</dt><dd>${escapeHTML(row.competition)}</dd></div><div><dt>Mean · uncertainty</dt><dd>${rating(row.mean)} · ±${rating(row.se)}</dd></div></dl></li>`;
    }).join("")}</ol>`;
  }

  function leaderRecordsHTML(rows) {
    const ordered = [...rows].reverse();
    return `<div class="record-desktop"><div class="table-shell"><table aria-label="World-comparable number one chronology"><thead><tr><th>Opening year</th><th>World-comparable No. 1</th><th class="numeric">Rating</th><th class="numeric">Uncertainty</th><th class="numeric">Published rank</th></tr></thead><tbody>${ordered.map((row) => `<tr><td>${row.year}</td><td>${clubIdentity(clubFor(row.club) || { code: row.club, name: row.name, country_name: row.country })}</td><td class="numeric"><span class="rating-main">${rating(row.rating)}</span></td><td class="numeric">±${rating(row.se)}</td><td class="numeric">${number(row.published_rank)}</td></tr>`).join("")}</tbody></table></div></div>
    <ol class="record-cards" aria-label="World-comparable number one chronology">${ordered.map((row) => `<li class="record-card"><header><span>${row.year}</span><strong>${rating(row.rating)}</strong></header>${clubIdentity(clubFor(row.club) || { code: row.club, name: row.name, country_name: row.country })}<dl><div><dt>Uncertainty</dt><dd>±${rating(row.se)}</dd></div><div><dt>Rank among all published clubs</dt><dd>${number(row.published_rank)}</dd></div></dl></li>`).join("")}</ol>`;
  }

  async function recordsPage() {
    setTitle("Records");
    loading("Loading club records…");
    const [records] = await Promise.all([getJSON("records.json"), getClubs()]);
    content.innerHTML = `
      <div class="page">
        ${pageHeading("Defined · guarded · reproducible", "Records", "Every list states its measure, ordering and eligibility. Peaks are post-match; upset probabilities are pre-match; world No. 1 is claimed only where the evidence network is comparable.")}
        <div class="record-tabs" role="tablist" aria-label="Record type">
          <button class="button button-dark" role="tab" data-record="peaks" aria-pressed="true" aria-selected="true">Club peaks</button>
          <button class="button" role="tab" data-record="strongest" aria-pressed="false" aria-selected="false">Highest-rated matches</button>
          <button class="button" role="tab" data-record="upsets" aria-pressed="false" aria-selected="false">Largest upsets</button>
          <button class="button" role="tab" data-record="aggregate" aria-pressed="false" aria-selected="false">Controlled second legs</button>
          <button class="button" role="tab" data-record="leaders" aria-pressed="false" aria-selected="false">World No. 1 chronology</button>
        </div>
        <div id="record-table"></div>
      </div>`;
    const target = document.getElementById("record-table");
    const draw = (name) => {
      const key = name === "strongest" ? "strongest_matches"
        : name === "aggregate" ? "aggregate_examples"
          : name === "leaders" ? "year_opening_number_ones" : name;
      const definition = records.definitions[key];
      target.innerHTML = `${recordDefinitionHTML(definition)}<div id="record-results"></div>`;
      const results = document.getElementById("record-results");
      if (name === "peaks") {
        results.innerHTML = peakRecordsHTML(records.peaks);
      } else if (name === "leaders") {
        results.innerHTML = leaderRecordsHTML(records.year_opening_number_ones);
      } else {
        renderPagedMatches(results, records[key].map(matchObject), 100, { recordType: name });
      }
      syncResponsivePresentation();
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
    const parameterRows = [
      ["Base rating", rating(p.base_rating), "Origin of the global club scale"],
      ["K factor", number(p.k_factor, 1), "Base size of an ordinary result update"],
      ["Domestic home advantage", signed(p.home_advantage_domestic, 1), "Home adjustment when both clubs share an association"],
      ["Cross-border home advantage", signed(p.home_advantage_cross_border, 1), "Home adjustment when the clubs represent different associations"],
      ["Draw peak", number(p.draw_peak, 3), "Maximum modeled draw probability at equal strength"],
      ["Margin scale", number(p.margin_scale, 2), "Diminishing extra influence for wins by more than one goal"],
      ["Club annual retention", number(p.club_retention, 2), "Club residual carried into the next calendar year"],
      ["Tier annual retention", number(p.tier_retention, 2), "Learned association-tier effect carried into the next year"],
      ["Tier update share", number(p.tier_share, 2), "Cross-tier domestic signal assigned to the two tier levels"],
      ["Tier baseline gap", rating(p.tier_gap), "Starting difference between adjacent domestic tiers"],
      ["Nation annual retention", number(p.country_retention, 2), "Association coefficient carried into the next year"],
      ["Nation update share", number(p.country_share, 2), "Cross-border signal assigned to the two associations"],
      ["Nation anchor", `${number(Number(p.country_anchor_quantile) * 100, 0)}th percentile`, "Elite-club anchor used inside each confederation"],
      ["Confederation annual retention", number(p.confederation_retention, 2), "Regional bridge carried into the next year"],
      ["Confederation update share", number(p.confederation_share, 2), "Inter-confederation signal assigned to the two regional bridges"],
      ["Extra-time weight", number(p.extra_time_weight, 2), "Evidence retained from an extra-time decision"],
      ["Penalty-decision weight", number(p.penalty_weight, 2), "Evidence retained from a shootout-decided draw"],
      ["Aggregate floor", number(p.aggregate_floor, 2), "Minimum weight for a controlled second-leg loss"],
      ["Aggregate scale", `${number(p.aggregate_scale, 2)} goals`, "How quickly aggregate leverage reduces second-leg information"],
      ["Evidence half-life", `${number(p.effective_matches_half_life_days, 0)} days`, "Recency decay used in uncertainty"],
      ["Club prior SD", rating(p.club_prior_sd), "Initial club uncertainty"],
      ["Tier prior SD", rating(p.tier_prior_sd), "Initial learned-tier uncertainty"],
      ["Nation prior SD", rating(p.country_prior_sd), "Initial association uncertainty"],
      ["Confederation prior SD", rating(p.confederation_prior_sd), "Initial regional-bridge uncertainty"],
      ["Uncertainty penalty", number(p.uncertainty_penalty, 2), "Standard errors subtracted from the forecast mean for publication"],
    ];
    const competitionRows = Object.entries(p.competition_weights || {})
      .map(([key, value]) => [slugLabel(key), number(value, 2)]);
    const correctionRows = Object.entries(meta.quality?.corrections || {});
    content.innerHTML = `
      <article class="page page-narrow prose methodology-page">
        ${pageHeading("Model · evidence · safeguards", "Methodology", "A complete description of the separate club replay: what enters it, how identities and ties are resolved, how every rating moves, and which claims the evidence is strong enough to publish.", true)}
        <nav class="method-contents" aria-label="Methodology sections">
          <a href="#/methodology?section=overview">Overview</a><a href="#/methodology?section=scope">Scope</a><a href="#/methodology?section=identity">Identity</a><a href="#/methodology?section=strength">Strength hierarchy</a><a href="#/methodology?section=tiers">Tiers</a><a href="#/methodology?section=venue">Venue</a><a href="#/methodology?section=probabilities">Probabilities</a><a href="#/methodology?section=learning">Result updates</a><a href="#/methodology?section=decisions">Extra time & penalties</a><a href="#/methodology?section=aggregate">Two-leg ties</a><a href="#/methodology?section=chronology">Chronology</a><a href="#/methodology?section=ratings">Published ratings</a><a href="#/methodology?section=records">Records</a><a href="#/methodology?section=coefficients">Coefficients</a><a href="#/methodology?section=validation">Validation</a><a href="#/methodology?section=limits">Limits</a>
        </nav>
        <section class="method-section" aria-labelledby="method-overview"><h2 id="method-overview" tabindex="-1">In plain English</h2><ol class="method-steps"><li><b>Keep the club primary.</b> A result chiefly changes the two clubs that played it.</li><li><b>Join otherwise separate leagues.</b> Cross-border matches estimate association strength; inter-confederation matches join the regional scales.</li><li><b>Respect competitive depth.</b> Domestic tiers have an explicit baseline and can learn from cross-tier cup evidence.</li><li><b>Predict before learning.</b> The archived W/D/L probabilities and ratings are frozen before the result is applied.</li><li><b>Judge a two-leg contest in context.</b> A controlled second-leg loss can carry less information when the losing club remains safely ahead on aggregate.</li><li><b>Publish cautiously.</b> The ranking subtracts uncertainty, so sparse or disconnected evidence cannot masquerade as world-leading certainty.</li></ol></section>
        <section class="method-section" aria-labelledby="method-scope"><h2 id="method-scope" tabindex="-1">Scope and source order</h2><p>The replay retains validated senior men’s competitive club results: domestic and state leagues, lower tiers, cups, playoffs, continental competitions, intercontinental competitions and global tournaments. Friendlies and future fixtures are outside this release.</p><p>Rows are normalized into one ledger, then merged by source priority. A higher-priority row can add a better score, venue, tier or identity; it cannot create a second copy of the same match. Current-season open league files repair promotion and relegation metadata, and a small reviewed layer can fill an important match only when it carries a direct authoritative source.</p></section>
        <section class="method-section" aria-labelledby="method-identity"><h2 id="method-identity" tabindex="-1">Club identity and duplicate control</h2><p>A normalized name is never a global identifier by itself. Identity resolution uses the name together with association, competition jurisdiction, season and curated aliases. That keeps same-named clubs in different countries separate and gives ambiguous historical successions separate records.</p><p>Competition-aware corrections can repair a bad country label when the competition makes the association unambiguous. Same-day home/away/score fingerprints, source references and explicit priorities remove duplicate rows. The build then rejects self-matches, unresolved associations and known cross-country collision signatures.</p></section>
        <section class="method-section" aria-labelledby="method-strength"><h2 id="method-strength" tabindex="-1">Club, tier, nation and confederation strength</h2><p>Each forecast mean is additive. The club remains the largest and most specific component; the other levels make sparse and cross-border comparisons possible without treating every domestic competition as equally strong.</p><div class="formula">mean = ${rating(p.base_rating)} + club residual + tier component + nation coefficient + confederation bridge<br>forecast difference = home mean − away mean + venue adjustment</div><details class="method-details"><summary>Why the nation anchor uses elite clubs</summary><p>Continental and global competitions select leading clubs rather than an average club from each association. Nation coefficients are therefore centred at the evidence-weighted ${number(Number(p.country_anchor_quantile) * 100, 0)}th percentile within each confederation. This stops a region receiving an artificial lift merely because it contains many weak leagues.</p></details></section>
        <section class="method-section" aria-labelledby="method-tiers"><h2 id="method-tiers" tabindex="-1">Domestic tiers, promotion and relegation</h2><p>Tier one is constrained to zero; each lower level begins ${rating(p.tier_gap)} points below the previous one. Cross-tier domestic cups and playoffs can learn a country-specific departure from that baseline. Recentring every learned tier gap on tier one is essential: a domestic cup can identify the distance between divisions, but cannot make an entire association stronger than another. A club’s current tier comes from the newest reliable league membership, not from the last source that happened to mention it.</p><div class="formula">tier component = −(tier − 1) × ${rating(p.tier_gap)} + learned gap relative to tier one</div><p>The club receives ${number((1 - Number(p.tier_share)) * 100, 0)}% of ordinary cross-tier learning and the tier levels share the remaining ${number(Number(p.tier_share) * 100, 0)}%. Current world rankings may contain lower-tier clubs, but guarded world-record lists and year-opening No. 1 claims require tier one.</p></section>
        <section class="method-section" aria-labelledby="method-venue"><h2 id="method-venue" tabindex="-1">Home, away and neutral</h2><p>Domestic home advantage is <b>${signed(p.home_advantage_domestic, 0)}</b> points. Cross-border home advantage is <b>${signed(p.home_advantage_cross_border, 0)}</b> points. Neutral and correctly identified global-tournament matches receive zero.</p><div class="formula">d = μhome − μaway + H<br>H = 0 at a neutral venue</div></section>
        <section class="method-section" aria-labelledby="method-probabilities"><h2 id="method-probabilities" tabindex="-1">Win, draw and loss probabilities</h2><p>The strength difference first becomes a logistic expected score. A draw curve then reaches its maximum when the clubs are equal and declines as the mismatch grows. The three displayed values are normalized to sum to 100%.</p><div class="formula">E = 1 / (1 + 10<sup>−d/400</sup>)<br>P(draw) = ${number(p.draw_peak, 3)} × 4E(1 − E)<br>P(home) = E − P(draw)/2 &nbsp; · &nbsp; P(away) = 1 − E − P(draw)/2</div><p>Forecasts use the underlying mean and venue adjustment. They do not use the cautious published rating, line-ups, injuries, travel, weather, rest or betting prices.</p></section>
        <section class="method-section" aria-labelledby="method-learning"><h2 id="method-learning" tabindex="-1">How a result changes the model</h2><p>The observed score is 1 for a home win, ½ for a draw and 0 for an away win. The residual between that score and the pre-match expectation is multiplied by competition, duration, aggregate and goal-margin factors.</p><div class="formula">Δ = K × competition weight × duration weight × aggregate weight × margin multiplier × (observed − expected)<br>margin multiplier = 1 + ${number(p.margin_scale, 2)} × ln(1 + winning margin − 1), for margins above one</div><p>Same-association, same-tier matches update the clubs. Cross-tier matches can also update tier levels. Cross-border matches can update association coefficients, and only inter-confederation evidence updates the regional bridge. The opposite sides receive equal and opposite changes at each active level.</p></section>
        <section class="method-section" aria-labelledby="method-decisions"><h2 id="method-decisions" tabindex="-1">Extra time, penalties and football scores</h2><p>An extra-time decision keeps ${number(Number(p.extra_time_weight) * 100, 0)}% of ordinary duration evidence. A penalty decision is a draw for rating purposes and keeps ${number(Number(p.penalty_weight) * 100, 0)}%. Shootout kicks are never added to the football score.</p><p>Some source rows declare a shootout but publish only a total that includes the kicks. When the regulation/extra-time score cannot be recovered safely, the ledger stores a <b>P?</b> decision: “Draw” is displayed instead of inventing a score, the source limitation is shown, and no goal-margin bonus is applied.</p></section>
        <section class="method-section" aria-labelledby="method-aggregate"><h2 id="method-aggregate" tabindex="-1">Two-leg ties and the Aggregate cases list</h2><p>The first leg is an ordinary match. A paired second leg keeps full weight when the tie was level, changes leader, ends level, or the match result confirms the aggregate leader. Only a controlled loss by a club that remains ahead is discounted.</p><div class="formula">weight = floor + (1 − floor) × max(exp(−|before margin| / scale), exp(−|after margin| / scale))<br>floor = ${number(p.aggregate_floor, 2)} &nbsp; · &nbsp; scale = ${number(p.aggregate_scale, 2)} goals</div><p>A 4–0 first leg followed by a controlled 0–1 loss retains about <b>${number(exampleWeight * 100, 1)}%</b> of ordinary second-leg information. The Records page’s <b>Controlled second legs</b> list contains precisely these discounted cases, ordered by lowest information weight. Its before/after margins use the second-leg home club’s perspective: positive means that club led the tie.</p></section>
        <section class="method-section" aria-labelledby="method-chronology"><h2 id="method-chronology" tabindex="-1">Chronology, same-day matches and annual carryover</h2><p>All forecasts on one calendar date use the same frozen start-of-day state. Their updates are accumulated and applied together, so file order cannot let one same-day match leak into another forecast. Post-match values shown for that date include the completed date batch.</p><p>At each calendar-year boundary, club, learned tier, nation and confederation components regress toward their priors using the disclosed retention factors. This limits permanent drift while preserving most established evidence. Uncertainty uses decayed effective match counts with a ${number(p.effective_matches_half_life_days, 0)}-day half-life.</p></section>
        <section class="method-section" aria-labelledby="method-ratings"><h2 id="method-ratings" tabindex="-1">The published rating</h2><div class="formula">rating = mean − ${number(p.uncertainty_penalty, 2)} × standard error</div><p>The mean powers forecasts. The lower confidence-adjusted rating powers current and historical rankings, club pages and post-match peaks. Ratings are always displayed with one decimal place and no thousands separator.</p></section>
        <section class="method-section" aria-labelledby="method-records"><h2 id="method-records" tabindex="-1">What every Records list means</h2><dl class="method-definition-list"><div><dt>Post-match club peaks</dt><dd>A club’s highest cautious rating immediately after a retained match, with at least ${number(meta.quality.world_comparable_min_matches)} results and uncertainty no greater than ${rating(meta.quality.world_comparable_max_se)}.</dd></div><div><dt>Highest-rated matches</dt><dd>The sum of both clubs’ cautious pre-match ratings; both uncertainties must clear the world-comparable ceiling.</dd></div><div><dt>Largest winning upsets</dt><dd>−ln(pre-match probability of the eventual winner). Draws, shootouts and low-evidence results are excluded.</dd></div><div><dt>Controlled second legs</dt><dd>The aggregate-context cases defined above, ordered by the smallest retained information weight.</dd></div><div><dt>Year-opening world No. 1</dt><dd>The highest eligible rating at the start of a year. The club must be active, tier one, have at least ${number(meta.quality.world_comparable_min_matches)} results and uncertainty no greater than ${rating(meta.quality.world_comparable_max_se)}. Years that cannot clear those safeguards are left unclaimed.</dd></div></dl><p>Historical peaks are always <b>post-match</b>. Match strength and upset probability are always <b>pre-match</b>. Those timing labels are part of the generated record definition and are tested before release.</p></section>
        <section class="method-section" aria-labelledby="method-coefficients"><h2 id="method-coefficients" tabindex="-1">Every release coefficient</h2><div class="table-hint" aria-hidden="true">Swipe horizontally to see every column →</div><div class="table-shell parameter-table"><table aria-label="Complete club model coefficients"><thead><tr><th>Coefficient</th><th class="numeric">Value</th><th>Role</th></tr></thead><tbody>${parameterRows.map(([name, value, role]) => `<tr><td>${escapeHTML(name)}</td><td class="numeric">${escapeHTML(value)}</td><td>${escapeHTML(role)}</td></tr>`).join("")}</tbody></table></div><h3>Competition multipliers</h3><div class="table-shell parameter-table"><table aria-label="Competition update multipliers"><thead><tr><th>Competition kind</th><th class="numeric">Multiplier</th></tr></thead><tbody>${competitionRows.map(([name, value]) => `<tr><td>${escapeHTML(name)}</td><td class="numeric">${escapeHTML(value)}</td></tr>`).join("")}</tbody></table></div></section>
        <section class="method-section" aria-labelledby="method-validation"><h2 id="method-validation" tabindex="-1">Release validation and update safety</h2><p><b>${escapeHTML(fit.status || "Chronological club replay")}.</b> ${escapeHTML(fit.selection || "")}</p><p>The installation builds a temporary ledger, replays the full chronology, generates a temporary static archive, and runs ledger, model, record and browser-data checks. Publication occurs only after every check passes, so a failed source refresh cannot mix old indexes with new club or match files.</p><ul><li>Identity, association, competition-jurisdiction and self-match checks.</li><li>Duplicate and score normalization checks, including shootout totals.</li><li>Probability-sum, chronology, venue and aggregate-pairing checks.</li><li>Current-tier, regional representation and uncertainty safeguards.</li><li>Named regression checks for known identity collisions, implausible historical leaders and the latest reviewed final.</li></ul>${correctionRows.length ? `<details class="method-details"><summary>Corrections made during this replay</summary><ul>${correctionRows.map(([name, value]) => `<li>${escapeHTML(slugLabel(name))}: ${number(value)}</li>`).join("")}</ul></details>` : ""}<div class="record-note"><strong>Release</strong><div><b>${escapeHTML(meta.model_version)}</b><br>${number(meta.matches)} retained matches from ${validDate(meta.first_result)} through ${validDate(meta.results_through)}; ${number(meta.active_clubs)} active clubs, ${number(meta.rated_clubs)} club histories and ${number(meta.associations)} associations. ${number(meta.quality.passed)} of ${number(meta.quality.checks)} ledger release checks passed.</div></div></section>
        <section class="method-section" aria-labelledby="method-limits"><h2 id="method-limits" tabindex="-1">Reproducibility and limits</h2><p>The installer rebuilds a temporary ledger, model database and static archive, validates them, then replaces the published version as a whole. A failed refresh leaves the previous site intact.</p><p>The model does not know line-ups, injuries, red cards, tactics, travel, rest, weather or betting markets. Historical identity resolution and incomplete competition coverage remain modelling limits.</p></section>
      </article>`;
    const requested = query.get("section");
    if (["overview", "scope", "identity", "strength", "tiers", "venue", "probabilities", "learning", "decisions", "aggregate", "chronology", "ratings", "records", "coefficients", "validation", "limits"].includes(requested)) {
      requestAnimationFrame(() => document.getElementById(`method-${requested}`)?.scrollIntoView({ block: "start" }));
    }
  }

  function faqItems() {
    return [
      ["What is the club rating?", "It is the cautious, uncertainty-adjusted estimate used for rankings, histories and records. It equals the underlying forecast mean minus 1.25 standard errors."],
      ["What is underlying strength?", "It is the model mean before the uncertainty deduction. Match forecasts use this value, the venue adjustment and the draw model; the public ranking does not."],
      ["Why do ratings look like 1867.4 rather than 1,867?", "Ratings follow the national NFELO convention: one decimal place and no thousands separator. Ordinary counts, such as matches or clubs, still use grouping separators."],
      ["Why can a lower-rated club be favoured in a forecast?", "The displayed ranking deliberately penalizes uncertainty. A forecast uses the fuller underlying mean plus venue, so a slightly lower cautious rating can still have the higher win probability."],
      ["Why are nation and confederation shown beneath each club?", "The club remains the large primary identity. Nation and confederation are smaller context labels and identify the two structural levels that connect otherwise separate domestic systems."],
      ["How can clubs from different continents be compared?", "Competitive continental matches estimate association strength inside each region. Inter-confederation and global matches bridge those regional scales. Sparse bridges retain visibly larger uncertainty."],
      ["Does a strong domestic league automatically receive a high coefficient?", "No. Its coefficient is learned from competitive cross-border results, anchored around elite clubs because continental competitions select elite clubs rather than a league-average team."],
      ["Can a lower-tier club appear in the rankings?", "Yes, if it has recent competitive evidence. Its tier baseline and uncertainty still apply. Guarded world-record lists and year-opening No. 1 claims require tier one."],
      ["How are promotions and relegations kept current?", "The newest complete domestic league membership files override stale tier labels from older cup or historical feeds. Cross-tier cup evidence then updates both the clubs and the relevant learned tier effects."],
      ["What does active mean?", "A club is active when it has a retained competitive result inside the published activity window. Historical clubs remain searchable on club and archive pages but are not mixed into the current active ranking."],
      ["What does provisional mean?", "The club has limited effective evidence and therefore larger uncertainty. The cautious rating automatically discounts it; provisional status is not a judgment about the club’s importance."],
      ["How is home advantage handled?", "The model has separate domestic and cross-border home adjustments. A verified neutral match receives no home adjustment, regardless of which club the source lists first."],
      ["What happens when two matches are played on the same date?", "Every probability on that date is calculated from one frozen start-of-day state. Updates are combined afterwards, so arbitrary source order cannot leak one result into another."],
      ["How are two-leg ties handled?", "The first leg is learned normally. A second leg keeps full weight unless it is a controlled loss by a club that remains ahead on aggregate; comebacks, level ties and confirming results keep ordinary weight."],
      ["What is the Controlled second legs or Aggregate cases list?", "It is the exact set of discounted second legs, ordered from lowest information weight. Before and after margins are stated from the second-leg home club’s perspective; positive means that club led the tie."],
      ["Why discount a controlled second-leg loss?", "A club that won the first leg 4–0 may rationally accept a 0–1 loss. Treating both legs as unrelated overstates the small loss; the 4–1 aggregate is stronger evidence of the tie’s balance."],
      ["Are penalty shootout kicks included in the score?", "No. The football score contains regulation and declared extra-time goals only. The shootout is a deciding status and is learned as a reduced-weight draw."],
      ["What does P? mean beside a match?", "The source says penalties decided the match but its numeric total mixes in shootout kicks and the exact football score cannot be recovered safely. The site displays Draw rather than inventing a score, preserves provenance and applies no margin bonus."],
      ["How is extra time handled?", "A result decided after extra time keeps 86% of ordinary duration evidence. Its football score may include declared extra-time goals, but it is explicitly labeled After extra time."],
      ["Are peaks measured before or after a match?", "After the match. A peak is the highest cautious post-match rating produced by a retained result, subject to the stated match-count and uncertainty safeguards."],
      ["What does Highest-rated matches measure?", "It adds the two clubs’ cautious ratings immediately before kick-off. Both clubs must clear the uncertainty ceiling. It measures the strength of the pairing, not spectacle or historical importance."],
      ["How is Largest upset calculated?", "It is minus the natural logarithm of the eventual winner’s pre-match win probability. Only decisive, sufficiently evidenced wins qualify; draws and penalty decisions do not."],
      ["What does year-opening world No. 1 mean?", "It is the highest eligible rating at the opening of that calendar year. The club must be active, tier one, sufficiently experienced and below the uncertainty ceiling. Unsupported early years are left without a claim."],
      ["Why might the historical No. 1 differ after an update?", "Newly recovered historical results, corrected identities or better competition metadata cause the entire chronology to replay. The model version, source hashes and results-through date identify each release."],
      ["How are same-named clubs kept apart?", "A name alone is never treated as a global identifier. Association, competition jurisdiction, season and curated aliases are part of resolution; known cross-country collision patterns are release-blocking checks."],
      ["How are duplicate results handled?", "Normalized date, clubs, score, competition and source fingerprints are merged under explicit source priorities. The final ledger must have unique match IDs and cannot contain a club playing itself."],
      ["Which matches are included?", "Validated competitive senior men’s domestic, state, lower-tier, cup, playoff, continental, intercontinental and global results are eligible. Friendlies are excluded."],
      ["Why might a club or result still be missing?", "Worldwide historical club data remain uneven. A row that cannot be assigned a safe identity, score or competition is withheld rather than allowed to corrupt the connected replay."],
      ["How can an important missing match be added?", "A small reviewed layer accepts the date, clubs, football score, competition, venue, decision status and a direct authoritative source. It passes the same identity, duplicate and model checks as bulk data."],
      ["Are upcoming fixtures included?", "No verified global fixture feed is connected. The Fixtures page says so explicitly and links to the current-state predictor instead of presenting stale or invented fixtures."],
      ["Can a data update partly break the published site?", "The installer builds and checks the ledger, replay and complete static archive before publication. Only a successful full build is committed, so old indexes cannot be mixed with new match or club files."],
      ["Is this a betting model?", "No. It is a results-only historical strength and prediction system. It does not account for line-ups, injuries, tactics, travel, rest, weather or market prices."],
      ["What should a correction report contain?", "Include both clubs, date, football score excluding shootout kicks, competition, venue, decision status and a reliable supporting URL in the project’s GitHub repository."],
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
    const [sources, competitions, meta] = await Promise.all([
      getJSON("sources.json"), getJSON("competitions.json"), getJSON("meta.json"),
    ]);
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
          <div class="panel"><p class="eyebrow">Results included through</p><h2>${validDate(bootstrap.meta.results_through)}</h2><p>${number(bootstrap.meta.matches)} matches across ${number(bootstrap.meta.rated_clubs)} club histories and ${number(bootstrap.meta.associations)} associations.</p><p class="muted small">Source data checked: ${validTimestamp(sources.runtime.retrieved_at)}<br>Site generated: ${validTimestamp(bootstrap.meta.generated_at)}<br>Model: ${escapeHTML(bootstrap.meta.model_version)}</p></div>
          <div class="panel panel-dark"><p class="eyebrow">Update safety</p><h2>Built before it replaces anything.</h2><p class="muted">Each refresh creates and validates temporary databases and a complete temporary static archive. Only a successful build replaces the live club data; a failed update leaves the previous site unchanged.</p></div>
        </section>
        <article class="section prose">
          <h2>Data sources</h2><p>The discovery starting point was <a href="${escapeHTML(sources.discovery_index.url)}" rel="external">${escapeHTML(sources.discovery_index.name)}</a>. The installation uses machine-readable feeds that can be schema-checked, attributed and traced to individual rows. Current OpenFootball league files repair 2025/26 promotion and relegation state; a reviewed, source-linked layer supplies the 30 May 2026 UEFA Champions League final where the bulk feeds stop short.</p>
          <div class="table-hint" aria-hidden="true">Swipe horizontally to see every column →</div><div class="table-shell"><table><thead><tr><th>Source family</th><th class="numeric">Files</th><th class="numeric">Downloaded</th><th>Licence / terms</th><th>Endpoint</th></tr></thead><tbody>${[...groups.values()].map((group) => `<tr><td><b>${escapeHTML(group.attribution)}</b></td><td class="numeric">${number(group.files)}</td><td class="numeric">${number(group.bytes / 1_000_000, 1)} MB</td><td>${escapeHTML(group.licence)}</td><td><a href="${escapeHTML(group.url)}" rel="external">Source endpoint</a></td></tr>`).join("")}</tbody></table></div>
          <h2>Retained coverage</h2><div class="table-hint" aria-hidden="true">Swipe horizontally to see every column →</div><div class="table-shell"><table aria-label="Retained club match coverage by source"><thead><tr><th>Source</th><th class="numeric">Matches</th><th>First</th><th>Last</th><th class="numeric">Competitions</th></tr></thead><tbody>${sources.coverage.map((row) => `<tr><td>${escapeHTML(row.source)}</td><td class="numeric">${number(row.matches)}</td><td>${validDate(row.first)}</td><td>${validDate(row.last)}</td><td class="numeric">${number(row.competitions)}</td></tr>`).join("")}</tbody></table></div>
          <h2>Competition scope</h2><p>The generated catalog currently contains ${number(competitions.competitions.length)} distinct competition keys. It spans domestic leagues and deep tiers, state championships, cups, playoffs, continental competitions and inter-confederation/global events.</p>
          <h2>Known limitations</h2><ul>${sources.limitations.map((item) => `<li>${escapeHTML(item)}</li>`).join("")}</ul>
          <h2>Quality checks</h2><p>This release passed ${number(meta.quality.passed)} of ${number(meta.quality.checks)} blocking ledger checks. Model and static-site checks then validate probabilities, current tiers, regional representation, guarded records and known regression cases.</p><div class="table-hint" aria-hidden="true">Swipe horizontally to see every column →</div><div class="table-shell"><table aria-label="Blocking club ledger quality checks"><thead><tr><th>Check</th><th class="numeric">Actual</th><th class="numeric">Expected</th><th>Status</th><th>Purpose</th></tr></thead><tbody>${sources.quality_checks.map((row) => `<tr><td>${escapeHTML(slugLabel(row.name))}</td><td class="numeric">${number(row.actual)}</td><td class="numeric">${number(row.expected)}</td><td><b>${row.passed ? "Passed" : "Failed"}</b></td><td>${escapeHTML(row.note)}</td></tr>`).join("")}</tbody></table></div>
          ${Object.keys(meta.quality.corrections || {}).length ? `<h3>Automatic source corrections in this replay</h3><ul>${Object.entries(meta.quality.corrections).map(([name, value]) => `<li>${escapeHTML(slugLabel(name))}: ${number(value)}</li>`).join("")}</ul>` : ""}
          <div class="callout"><b>One result, one trace.</b> Every archive row retains its source family and source reference. The complete formulas, timing rules, coefficients and record eligibility gates are published on <a href="#/methodology">Methodology</a>.</div>
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
    document.body.dataset.pageFamily = PAGE_FAMILIES[name] || "ledger";
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
      syncResponsivePresentation();
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
  window.addEventListener("resize", syncResponsivePresentation, { passive: true });
  window.addEventListener("orientationchange", syncResponsivePresentation, { passive: true });
  route();
})();
