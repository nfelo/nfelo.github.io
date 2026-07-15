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
  const rating = (value) => value == null ? "—" : Number(value).toLocaleString("en", {
    minimumFractionDigits: 1,
    maximumFractionDigits: 1,
    useGrouping: false,
  });
  const percent = (value) => `${number(value * 100, 1)}%`;
  const todayISO = () => {
    const today = new Date();
    return `${today.getFullYear()}-${String(today.getMonth() + 1).padStart(2, "0")}-${String(today.getDate()).padStart(2, "0")}`;
  };
  const validDate = (value) => {
    const [year, month, day] = String(value).split("-");
    if (month === "00") return year;
    if (day === "00") return `${month}/${year}`;
    const parsed = new Date(`${value}T00:00:00Z`);
    return Number.isNaN(parsed.valueOf()) ? value : `${day}/${month}/${year}`;
  };
  const fixtureDate = (fixture) => fixture.date_precision === "month"
    ? `Date TBC · ${new Date(`${fixture.date}T00:00:00Z`).toLocaleDateString("en-GB", { month: "short", year: "numeric", timeZone: "UTC" }).toUpperCase()}`
    : validDate(fixture.date);
  const fixtureSite = (fixture) => Number(fixture.home_sign) === 1 ? "H" : Number(fixture.home_sign) === -1 ? "A" : "N";
  const validTimestamp = (value) => {
    const parsed = new Date(value);
    return Number.isNaN(parsed.valueOf())
      ? "—"
      : parsed.toLocaleString("en-GB", {
          year: "numeric", month: "short", day: "numeric",
          hour: "2-digit", minute: "2-digit", timeZone: "UTC", timeZoneName: "short",
        });
  };
  const teamURL = (code, date = "") => `#/team/${encodeURIComponent(code)}${date ? `?date=${encodeURIComponent(date)}` : ""}`;
  const teamLink = (code, name, date = "") => `<a class="team-link" href="${teamURL(code, date)}">${escapeHTML(name)}</a>`;
  const cleanRouteURL = (section, value = "", query = new URLSearchParams()) => {
    const path = [section === "home" ? "" : section, value].filter(Boolean).map(encodeURIComponent).join("/");
    const suffix = query.toString();
    return `${new URL(path ? `${path}/` : "", document.baseURI).pathname}${suffix ? `?${suffix}` : ""}`;
  };
  const replaceRouteQuery = (section, values) => {
    const query = new URLSearchParams();
    Object.entries(values).forEach(([key, value]) => { if (value !== "" && value != null) query.set(key, value); });
    history.replaceState(null, "", cleanRouteURL(section, "", query));
  };

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

  function setRouteMetadata(route) {
    const descriptions = {
      home: "International football ratings, historical results, records and match probabilities from 1872 to the present.",
      rankings: "Current international football rankings from the Network Football Elo model.",
      history: "Reconstruct international football rankings on any historical matchday.",
      matches: "Search international football results and pre-match forecasts from 1872 onward.",
      fixtures: "Upcoming senior internationals with current ratings and match probabilities.",
      records: "All-time national-team rating peaks, greatest matchups and largest upsets.",
      predict: "Compare two national teams and calculate win, draw and loss probabilities.",
      methodology: "Detailed, reproducible methodology for the Network Football Elo model.",
      about: "Data sources, update schedule and limitations of Network Football Elo.",
      team: `${document.querySelector("h1")?.textContent || "National team"} ratings, results and historical record.`,
    };
    const description = descriptions[route.section] || descriptions.home;
    const canonical = new URL(cleanRouteURL(route.section, route.value, route.query), location.origin).href;
    document.querySelector('meta[name="description"]')?.setAttribute("content", description);
    document.querySelector('link[rel="canonical"]')?.setAttribute("href", canonical);
    document.querySelector('meta[property="og:title"]')?.setAttribute("content", document.title);
    document.querySelector('meta[property="og:description"]')?.setAttribute("content", description);
    document.querySelector('meta[property="og:url"]')?.setAttribute("content", canonical);
    document.querySelector('meta[name="twitter:title"]')?.setAttribute("content", document.title);
    document.querySelector('meta[name="twitter:description"]')?.setAttribute("content", description);
  }

  function parseRoute() {
    const basePath = new URL(document.baseURI).pathname.replace(/\/?$/, "/");
    const pathRoute = location.pathname.startsWith(basePath) ? location.pathname.slice(basePath.length).replace(/^\/|\/$/g, "") : "";
    const raw = location.hash.startsWith("#/") ? location.hash.slice(2) : `${pathRoute}${location.search}`;
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

  const isoDate = (value) => {
    const parsed = new Date(`${value}T00:00:00Z`);
    return Number.isNaN(parsed.valueOf()) ? "" : parsed.toISOString().slice(0, 10);
  };
  const inputDate = (value) => {
    const match = String(value).trim().match(/^(\d{1,2})\/(\d{1,2})\/(\d{4})$/);
    if (!match) return "";
    const [, rawDay, rawMonth, year] = match;
    const day = rawDay.padStart(2, "0");
    const month = rawMonth.padStart(2, "0");
    const iso = `${year}-${month}-${day}`;
    const parsed = new Date(`${iso}T00:00:00Z`);
    return Number.isNaN(parsed.valueOf()) || parsed.toISOString().slice(0, 10) !== iso ? "" : iso;
  };
  const venueHTML = (code) => {
    const labels = { H: "Home", A: "Away", N: "Neutral" };
    return `<span class="venue-code venue-${code}" title="${labels[code]}" aria-label="${labels[code]}">${code}</span>`;
  };

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

  function poissonWDL(lambdaA, lambdaB) {
    const first = [Math.exp(-lambdaA)];
    const second = [Math.exp(-lambdaB)];
    for (let goals = 1; goals <= 40; goals += 1) {
      first.push(first[goals - 1] * lambdaA / goals);
      second.push(second[goals - 1] * lambdaB / goals);
    }
    let win = 0;
    let draw = 0;
    let loss = 0;
    let firstBelow = first[0];
    let secondBelow = second[0];
    draw += first[0] * second[0];
    for (let goals = 1; goals <= 40; goals += 1) {
      win += first[goals] * secondBelow;
      loss += second[goals] * firstBelow;
      draw += first[goals] * second[goals];
      firstBelow += first[goals];
      secondBelow += second[goals];
    }
    const total = win + draw + loss;
    return [win / total, draw / total, loss / total];
  }

  function applyForecastLayer(base, expected, first, second, friendly, day, layer) {
    if (!layer) return base;
    const decayRate = layer.parameters.annual_decay;
    const decayed = (values, team) => {
      const previous = layer.last_day[team];
      const elapsed = previous < 0 ? 0 : Math.max(0, (day - previous) / 400);
      return values[team] * Math.exp(-decayRate * elapsed);
    };
    const clipped = Math.min(1 - 1e-8, Math.max(1e-8, expected));
    const gap = 0.5 * layer.parameters.gap_scale * Math.log(clipped / (1 - clipped));
    const attackA = decayed(layer.attack, first);
    const attackB = decayed(layer.attack, second);
    const defenceA = decayed(layer.defence, first);
    const defenceB = decayed(layer.defence, second);
    const lambdaA = Math.min(8, Math.max(0.05, Math.exp(Math.log(layer.base_goal) + gap + attackA - defenceB)));
    const lambdaB = Math.min(8, Math.max(0.05, Math.exp(Math.log(layer.base_goal) - gap + attackB - defenceA)));
    const score = poissonWDL(lambdaA, lambdaB);
    score[1] *= Math.exp(layer.calibration.draw_log_tilt);
    let total = score.reduce((sum, value) => sum + value, 0);
    const temperature = friendly
      ? layer.calibration.friendly_temperature
      : layer.calibration.competitive_temperature;
    const calibrated = score.map((value) => Math.pow(Math.max(1e-15, value / total), temperature));
    total = calibrated.reduce((sum, value) => sum + value, 0);
    const normalised = calibrated.map((value) => value / total);
    const pooled = base.map((value, index) => (
      layer.calibration.nfelo_weight * value
      + layer.calibration.score_weight * normalised[index]
    ));
    const top = (values) => values.indexOf(Math.max(...values));
    return top(pooled) === top(base) ? pooled : base;
  }

  async function renderHome() {
    setTitle("");
    const topTen = summary.current.slice(0, 10);
    const fixturePayload = await getJSON("data/fixtures.json");
    const nextFixtures = (fixturePayload.fixtures || []).slice(0, 5);
    content.innerHTML = `
      <div class="page home-page">
        <section class="home-intro">
          <div class="home-intro-copy">
          <p class="eyebrow">A predictive rating, rebuilt from 1872</p>
          <h1>International football, ranked in context.</h1>
          <p class="lede">International results since 1872 are used to estimate each team's strength. The model follows connections through shared opponents and allows for uncertainty when teams have played few or geographically limited opponents.</p>
          <div class="hero-actions">
            <a class="button button-primary" href="#/rankings">See the rankings</a>
            <a class="button" href="#/fixtures">Upcoming matches</a>
            <a class="button" href="#/predict">Try a matchup</a>
          </div>
          </div>
          <dl class="home-facts">
            <div><dt>Latest result</dt><dd>${validDate(summary.meta.results_through)}</dd></div>
            <div><dt>Matches</dt><dd>${number(summary.meta.matches)}</dd></div>
            <div><dt>Teams</dt><dd>${number(summary.meta.teams)}</dd></div>
            <div><dt>Forecast accuracy</dt><dd>${percent(summary.validation.accuracy)}</dd></div>
          </dl>
        </section>

        <section class="home-dashboard">
          <div class="home-ranking-list">
            <div class="compact-heading"><div><p class="eyebrow">Current rankings</p><h2>Top ten</h2></div><a href="#/rankings">Full rankings →</a></div>
            <ol>${topTen.map((team, index) => `<li><span class="home-rank">${index + 1}</span><a href="${teamURL(team.code)}">${escapeHTML(team.nation)}</a><strong>${rating(team.rating)}</strong><small>±${rating(team.se)}</small></li>`).join("")}</ol>
          </div>
          <aside class="home-upcoming">
            <div class="compact-heading"><div><p class="eyebrow">Next matches</p><h2>Upcoming</h2></div><a href="#/fixtures">All fixtures →</a></div>
            ${nextFixtures.length ? `<ul>${nextFixtures.map((fixture) => `<li><time>${fixtureDate(fixture)}</time><span>${teamLink(fixture.team1_code, fixture.team1_name)} <i>v</i> ${teamLink(fixture.team2_code, fixture.team2_name)}</span><small>${escapeHTML(fixture.tournament_name)}</small></li>`).join("")}</ul>` : `<p class="muted">No identified fixtures in the current feeds.</p>`}
          </aside>
        </section>

        <section class="home-support">
          <div>
            <p class="eyebrow">What makes it different</p><h2>Opponents—and their opponents—matter.</h2>
            <p>Beating a strong side counts for more. Shared opponents connect regions and eras, while uncertainty stops isolated teams being overrated.</p>
            <a href="#/methodology">Read the methodology →</a>
          </div>
          <div class="home-records">
            <div class="compact-heading"><div><p class="eyebrow">Record book</p><h2>Greatest matchups</h2></div><a href="#/records">All records →</a></div>
            <ol>${summary.top_matches.slice(0, 5).map((match, index) => `<li><span>${index + 1}</span><div>${teamLink(match.code1, match.team1)} <i>v</i> ${teamLink(match.code2, match.team2)}<small>${validDate(match.date)}</small></div><strong>${rating(match.combined)}</strong></li>`).join("")}</ol>
          </div>
        </section>
      </div>`;
  }

  function rankingsTable(items, showRank) {
    if (!items.length) return `<div class="empty">No teams match those filters.</div>`;
    return `<div class="table-shell"><table>
      <thead><tr><th class="numeric">Rank</th><th>Team</th><th class="numeric">Rating</th><th class="numeric hide-mobile">Model strength</th><th class="numeric hide-mobile">Matches</th><th>Recent form</th><th class="hide-mobile">All-time peak</th></tr></thead>
      <tbody>${items.map((team, index) => `<tr>
        <td class="rank-cell numeric">${showRank ? team.display_rank ?? team.rank ?? index + 1 : index + 1}</td>
        <td>${teamLink(team.code, team.nation)}</td>
        <td class="numeric"><span class="rating-main">${rating(team.rating)}</span><span class="rating-sub">uncertainty ${rating(team.se)}</span></td>
        <td class="numeric hide-mobile">${rating(team.mean)}</td>
        <td class="numeric hide-mobile">${number(team.matches)}</td>
        <td>${formHTML(team.form || [])}</td>
        <td class="hide-mobile">${team.peak ? `${rating(team.peak.rating)} · ${validDate(team.peak.date)}` : "—"}</td>
      </tr>`).join("")}</tbody>
    </table></div>`;
  }

  function renderRankings(route) {
    setTitle("Rankings");
    content.innerHTML = `
      <div class="page">
        <header class="page-heading"><div><p class="eyebrow">Current international teams</p><h1>Rankings</h1></div><p class="lede">The rating combines estimated playing strength with an allowance for uncertainty. Teams with results against a broad range of opponents can therefore be assessed more confidently. <a href="#/history">Choose a historical date →</a></p></header>
        <div class="toolbar">
          <div class="field field-grow"><label for="ranking-search">Find a team</label><input id="ranking-search" type="search" placeholder="Spain, Argentina, Japan…" value="${escapeHTML(route.query.get("q") || "")}"></div>
          <div class="field"><label for="ranking-sort">Sort</label><select id="ranking-sort"><option value="rating">Rating</option><option value="mean">Model strength</option><option value="matches">Matches played</option><option value="name">Name</option></select></div>
          <div class="toggle-group" role="group" aria-label="Ranking pool"><button class="button" data-pool="current" aria-pressed="false">Current</button><button class="button" data-pool="all" aria-pressed="false">All histories</button></div>
        </div>
        <div class="record-note"><strong>Rating</strong><div>The published rating is the model's strength estimate adjusted for the range of opponents played and the uncertainty in that estimate. A team must have played at least 30 matches and appeared within the last four years to enter the current table.</div></div>
        <div id="rankings-table"></div>
      </div>`;
    const target = document.getElementById("rankings-table");
    let pool = route.query.get("pool") === "all" ? "all" : "current";
    const requestedSort = ["rating", "mean", "matches", "name"].includes(route.query.get("sort")) ? route.query.get("sort") : "rating";
    document.getElementById("ranking-sort").value = requestedSort;
    document.querySelectorAll("[data-pool]").forEach((button) => {
      const selected = button.dataset.pool === pool;
      button.setAttribute("aria-pressed", String(selected));
      button.classList.toggle("button-dark", selected);
    });
    const save = () => replaceRouteQuery("rankings", {
      q: document.getElementById("ranking-search").value.trim(),
      sort: document.getElementById("ranking-sort").value === "rating" ? "" : document.getElementById("ranking-sort").value,
      pool: pool === "current" ? "" : pool,
    });
    const update = () => {
      const query = document.getElementById("ranking-search").value.trim().toLocaleLowerCase();
      const sort = document.getElementById("ranking-sort").value;
      const source = pool === "current" ? summary.current : summary.teams;
      const ratingRanks = new Map([...source].sort((a, b) => b.rating - a.rating || a.nation.localeCompare(b.nation)).map((team, index) => [team.code, index + 1]));
      const filtered = source.filter((team) => team.nation.toLocaleLowerCase().includes(query));
      filtered.sort((a, b) => sort === "name"
        ? a.nation.localeCompare(b.nation)
        : (b[sort] ?? -Infinity) - (a[sort] ?? -Infinity) || a.nation.localeCompare(b.nation));
      target.innerHTML = rankingsTable(filtered.map((team) => ({ ...team, display_rank: ratingRanks.get(team.code) })), true);
    };
    document.getElementById("ranking-search").addEventListener("input", () => { save(); update(); });
    document.getElementById("ranking-sort").addEventListener("change", () => { save(); update(); });
    document.querySelectorAll("[data-pool]").forEach((button) => button.addEventListener("click", () => {
      pool = button.dataset.pool;
      document.querySelectorAll("[data-pool]").forEach((peer) => {
        const selected = peer === button;
        peer.setAttribute("aria-pressed", String(selected));
        peer.classList.toggle("button-dark", selected);
      });
      save();
      update();
    }));
    update();
  }

  function historicalRankingsTable(items, selectedDate) {
    if (!items.length) return `<div class="empty"><h2>No eligible rankings yet</h2><p>Teams enter the table after their 30th recorded match.</p></div>`;
    return `<div class="table-hint" aria-hidden="true">Swipe to see more →</div><div class="table-shell"><table>
      <thead><tr><th class="numeric">Rank</th><th>Team</th><th class="numeric">Rating</th><th class="numeric hide-mobile">Model strength</th><th class="numeric hide-mobile">Matches</th><th>Recent form</th><th class="hide-mobile">Last match</th></tr></thead>
      <tbody>${items.map((team, index) => `<tr><td class="rank-cell numeric">${team.rank ?? index + 1}</td><td>${teamLink(team.code, team.nation, selectedDate)}</td>
        <td class="numeric"><span class="rating-main">${rating(team.rating)}</span><span class="rating-sub">uncertainty ${rating(team.se)}</span></td>
        <td class="numeric hide-mobile">${rating(team.mean)}</td><td class="numeric hide-mobile">${number(team.matches)}</td>
        <td>${formHTML(team.form || [])}</td><td class="hide-mobile">${validDate(team.date)}</td></tr>`).join("")}</tbody></table></div>`;
  }

  async function renderHistory(route) {
    setTitle("Historical rankings");
    loading("Loading historical rankings…");
    const index = await getJSON("data/rankings-history/index.json");
    const today = todayISO();
    const requested = isoDate(route.query.get("date")) || today;
    const selected = requested < index.first ? index.first : requested > today ? today : requested;
    content.innerHTML = `<div class="page">
      <header class="page-heading"><div><p class="eyebrow">Rankings on any date</p><h1>Historical rankings</h1></div><p class="lede">Reconstructed with the current model after every match played on or before the selected date. These are present-day estimates of the past, not tables published at the time.</p></header>
      <div class="toolbar history-toolbar">
        <div class="history-date-actions"><div class="field history-date-field"><label for="history-date">Ranking date</label><div class="date-combo"><input id="history-date" type="text" inputmode="numeric" autocomplete="off" placeholder="DD/MM/YYYY" value="${validDate(selected)}" aria-describedby="history-date-error"><button class="button" type="button" id="history-calendar-button" aria-label="Open calendar">Calendar</button><input id="history-calendar" class="native-date-proxy" type="date" min="${index.first}" max="${today}" value="${selected}" tabindex="-1" aria-hidden="true" aria-label="Ranking date calendar"></div><span id="history-date-error" class="field-error" role="alert"></span></div><button class="button button-dark" type="button" id="history-apply">Apply date</button></div>
        <div class="history-nav-actions"><button class="button" type="button" id="history-prev">← Previous matchday</button><button class="button" type="button" id="history-next">Next matchday →</button><button class="button" type="button" id="history-year-start">Start of year</button></div>
        <div class="field field-grow"><label for="history-world-cup">World Cup moments</label><select id="history-world-cup"><option value="">Choose a tournament…</option>${index.world_cups.flatMap((cup) => [`<option value="${cup.before}">Before ${cup.year} World Cup</option>`, `<option value="${cup.after}">After ${cup.year} World Cup</option>`]).join("")}</select></div>
      </div>
      <div class="record-note"><strong id="history-count">—</strong><div><b id="history-label">Eligible teams</b><br>At least 30 matches and an appearance in the selected year or preceding four calendar years.</div></div>
      <div class="toolbar compact-toolbar"><div class="field field-grow"><label for="history-search">Find a team</label><input id="history-search" type="search" placeholder="Brazil, Hungary, Morocco…" value="${escapeHTML(route.query.get("q") || "")}"></div><div class="field"><label for="history-sort">Sort</label><select id="history-sort"><option value="rating">Rating</option><option value="mean">Model strength</option><option value="matches">Matches played</option><option value="name">Name</option></select></div></div>
      <div id="history-table"></div></div>`;

    let teams = [];
    let currentDate = selected;
    const dateInput = document.getElementById("history-date");
    const calendarInput = document.getElementById("history-calendar");
    const table = document.getElementById("history-table");
    const requestedSort = ["rating", "mean", "matches", "name"].includes(route.query.get("sort")) ? route.query.get("sort") : "rating";
    document.getElementById("history-sort").value = requestedSort;
    const saveHistoryRoute = () => replaceRouteQuery("history", {
      date: currentDate,
      q: document.getElementById("history-search").value.trim(),
      sort: document.getElementById("history-sort").value === "rating" ? "" : document.getElementById("history-sort").value,
    });
    const updateTable = () => {
      const query = document.getElementById("history-search").value.trim().toLocaleLowerCase();
      const sort = document.getElementById("history-sort").value;
      const visible = teams.filter((team) => team.nation.toLocaleLowerCase().includes(query));
      visible.sort((a, b) => sort === "name" ? a.nation.localeCompare(b.nation) : (b[sort] ?? -Infinity) - (a[sort] ?? -Infinity) || a.nation.localeCompare(b.nation));
      table.innerHTML = historicalRankingsTable(visible, currentDate);
    };
    const loadDate = async (value) => {
      const chosen = value < index.first ? index.first : value > today ? today : value;
      currentDate = chosen;
      dateInput.value = validDate(chosen);
      calendarInput.value = chosen;
      document.getElementById("history-date-error").textContent = "";
      document.getElementById("history-prev").disabled = chosen <= index.first;
      document.getElementById("history-next").disabled = chosen >= index.last;
      saveHistoryRoute();
      table.innerHTML = `<div class="loading-shell"><span class="spinner"></span><p>Loading ${escapeHTML(validDate(chosen))}…</p></div>`;
      const dataYear = Math.min(Number(chosen.slice(0, 4)), Number(index.last.slice(0, 4)));
      const payload = await getJSON(`data/rankings-history/${dataYear}.json`);
      const state = new Map(payload.opening.map((team) => [team.code, team]));
      payload.events.forEach((event) => { if (event.date <= chosen) state.set(event.code, event); });
      const year = Number(chosen.slice(0, 4));
      teams = [...state.values()].filter((team) => year - Number(team.date.slice(0, 4)) <= 4);
      teams.sort((a, b) => b.rating - a.rating || a.nation.localeCompare(b.nation));
      teams.forEach((team, index) => { team.rank = index + 1; });
      document.getElementById("history-count").textContent = number(teams.length);
      document.getElementById("history-label").textContent = `Eligible teams on ${validDate(chosen)}`;
      updateTable();
    };
    const adjacentMatchday = async (direction) => {
      let chosen = currentDate;
      let year = Number(chosen.slice(0, 4));
      const firstYear = Number(index.first.slice(0, 4));
      const lastYear = Number(index.last.slice(0, 4));
      while (year >= firstYear && year <= lastYear) {
        const payload = await getJSON(`data/rankings-history/${year}.json`);
        const candidates = payload.matchdays.filter((day) => direction < 0 ? day < chosen : day > chosen);
        if (candidates.length) return loadDate(direction < 0 ? candidates[candidates.length - 1] : candidates[0]);
        year += direction;
        chosen = direction < 0 ? `${year + 1}-01-01` : `${year - 1}-12-31`;
      }
    };
    const applyTypedDate = () => {
      const chosen = inputDate(dateInput.value);
      if (!chosen) {
        document.getElementById("history-date-error").textContent = "Enter a valid date as DD/MM/YYYY.";
        return;
      }
      loadDate(chosen);
    };
    document.getElementById("history-apply").addEventListener("click", applyTypedDate);
    dateInput.addEventListener("keydown", (event) => { if (event.key === "Enter") applyTypedDate(); });
    document.getElementById("history-calendar-button").addEventListener("click", () => {
      if (typeof calendarInput.showPicker === "function") calendarInput.showPicker();
      else calendarInput.click();
    });
    calendarInput.addEventListener("change", () => { if (calendarInput.value) loadDate(calendarInput.value); });
    document.getElementById("history-year-start").addEventListener("click", () => loadDate(`${currentDate.slice(0, 4)}-01-01`));
    document.getElementById("history-prev").addEventListener("click", () => adjacentMatchday(-1));
    document.getElementById("history-next").addEventListener("click", () => adjacentMatchday(1));
    document.getElementById("history-world-cup").addEventListener("change", (event) => { if (event.target.value) loadDate(event.target.value); });
    document.getElementById("history-search").addEventListener("input", () => { saveHistoryRoute(); updateTable(); });
    document.getElementById("history-sort").addEventListener("change", () => { saveHistoryRoute(); updateTable(); });
    await loadDate(selected);
  }

  async function renderMatches(route) {
    setTitle("Matches");
    loading("Loading the historical match explorer…");
    const index = await getJSON("data/matches/index.json");
    const requestedTeam = route.query.get("team") || "";
    const latest = index.decades[index.decades.length - 1].decade;
    content.innerHTML = `
      <div class="page">
        <header class="page-heading"><div><p class="eyebrow">International results since 1872</p><h1>Matches</h1></div><p class="lede">Browse the complete match history. Probabilities and ratings are calculated using only information available before each match.</p></header>
        <div class="toolbar">
          <div class="field"><label for="match-decade">Era</label><select id="match-decade"><option value="all">All ${number(summary.meta.matches)} matches</option>${index.decades.slice().reverse().map((item) => `<option value="${item.decade}">${item.decade}s · ${number(item.count)}</option>`).join("")}</select></div>
          <div class="field"><label for="match-team">Team</label><select id="match-team"><option value="">Any team</option>${summary.teams.map((team) => `<option value="${escapeHTML(team.code)}" ${team.code === requestedTeam ? "selected" : ""}>${escapeHTML(team.nation)}</option>`).join("")}</select></div>
          <div class="field"><label for="match-class">Class</label><select id="match-class"><option value="">All classes</option><option value="friendly">Friendly</option><option value="competitive">Competitive</option></select></div>
          <div class="field field-grow"><label for="match-search">Competition or opponent</label><input id="match-search" type="search" placeholder="World Cup, England, qualifier…" value="${escapeHTML(route.query.get("q") || "")}"></div>
        </div>
        <p id="match-count" class="muted small"></p>
        <div class="pagination match-pagination" aria-label="Match pages">
          <button id="match-newest" class="button">⇤ Newest</button>
          <button id="match-prev" class="button">← Newer</button>
          <span id="match-page" class="muted small" aria-live="polite"></span>
          <button id="match-next" class="button">Older →</button>
          <button id="match-oldest" class="button">Oldest ⇥</button>
        </div>
        <div id="match-table"></div>
      </div>`;

    let rows = [];
    let page = Math.max(0, Number(route.query.get("page") || 1) - 1) || 0;
    const pageSize = 100;
    const validDecades = new Set(index.decades.map((item) => String(item.decade)));
    const initialDecade = route.query.get("era") === "all" || validDecades.has(route.query.get("era")) ? route.query.get("era") : String(latest);
    document.getElementById("match-decade").value = initialDecade;
    if (route.query.get("class") === "friendly" || route.query.get("class") === "competitive") document.getElementById("match-class").value = route.query.get("class");
    const saveMatchesRoute = () => replaceRouteQuery("matches", {
      era: document.getElementById("match-decade").value === String(latest) ? "" : document.getElementById("match-decade").value,
      team: document.getElementById("match-team").value,
      class: document.getElementById("match-class").value,
      q: document.getElementById("match-search").value.trim(),
      page: page ? page + 1 : "",
    });
    const load = async () => {
      const decade = document.getElementById("match-decade").value;
      loadingTable();
      if (decade === "all") {
        rows = (await getJSON("data/matches/search.json")).matches.slice().reverse();
      } else {
        rows = (await getJSON(`data/matches/${decade}.json`)).matches.slice().reverse();
      }
      await update();
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
    let updateToken = 0;
    const update = async () => {
      const token = ++updateToken;
      const result = filtered();
      const pages = Math.max(1, Math.ceil(result.length / pageSize));
      page = Math.min(page, pages - 1);
      const visible = result.slice(page * pageSize, (page + 1) * pageSize);
      document.getElementById("match-count").textContent = `${number(result.length)} matches`;
      document.getElementById("match-page").textContent = `Page ${page + 1} of ${pages}`;
      document.getElementById("match-prev").disabled = page === 0;
      document.getElementById("match-next").disabled = page >= pages - 1;
      document.getElementById("match-newest").disabled = page === 0;
      document.getElementById("match-oldest").disabled = page >= pages - 1;
      let hydrated = visible;
      if (document.getElementById("match-decade").value === "all" && visible.length) {
        loadingTable();
        const decades = [...new Set(visible.map((match) => match.decade))];
        const chunks = await Promise.all(decades.map((decade) => getJSON(`data/matches/${decade}.json`)));
        if (token !== updateToken) return;
        const byId = new Map(chunks.flatMap((chunk) => chunk.matches).map((match) => [match.id, match]));
        hydrated = visible.map((match) => byId.get(match.id)).filter(Boolean);
      }
      document.getElementById("match-table").innerHTML = matchTable(hydrated, document.getElementById("match-team").value);
      saveMatchesRoute();
    };
    document.getElementById("match-decade").addEventListener("change", () => { page = 0; load(); });
    document.getElementById("match-team").addEventListener("change", () => { page = 0; update(); });
    document.getElementById("match-class").addEventListener("change", () => { page = 0; update(); });
    document.getElementById("match-search").addEventListener("input", () => { page = 0; update(); });
    document.getElementById("match-prev").addEventListener("click", () => { page -= 1; update(); scrollTo({ top: 0, behavior: "smooth" }); });
    document.getElementById("match-next").addEventListener("click", () => { page += 1; update(); scrollTo({ top: 0, behavior: "smooth" }); });
    document.getElementById("match-newest").addEventListener("click", () => { page = 0; update(); });
    document.getElementById("match-oldest").addEventListener("click", () => { page = Math.max(0, Math.ceil(filtered().length / pageSize) - 1); update(); });
    await load();
  }

  function matchSite(match, perspective = "") {
    if (match.home === 0) return "N";
    if (perspective === match.b) return match.home === -1 ? "H" : "A";
    return match.home === 1 ? "H" : "A";
  }

  function matchTable(matches, perspective = "") {
    if (!matches.length) return `<div class="empty">No matches found.</div>`;
    return `<div class="table-shell match-history-table"><table><thead><tr><th>Date</th><th>Match</th><th>H/A/N</th><th class="numeric">Score</th><th class="hide-mobile">Competition</th><th>Pre-match W/D/L</th><th>Team ratings before → after</th><th class="numeric">Combined pre-match rating</th></tr></thead><tbody>${matches.map((match) => `<tr>
      <td class="mono" data-label="Date">${validDate(match.date)}</td>
      <td data-label="Match">${teamLink(match.a, match.an)} <span class="muted">v</span> ${teamLink(match.b, match.bn)}</td>
      <td data-label="Venue">${venueHTML(matchSite(match, perspective))}</td>
      <td class="numeric" data-label="Score"><span class="score">${match.sa}–${match.sb}</span></td>
          <td class="hide-mobile" data-label="Competition">${escapeHTML(match.t)}</td>
      <td data-label="Forecast">${probabilityHTML(match.p)}</td>
      <td data-label="Team ratings"><span class="rating-pair"><b>${escapeHTML(match.an)}</b> ${rating(match.pre_a)} → ${rating(match.post_a)}</span><span class="rating-pair"><b>${escapeHTML(match.bn)}</b> ${rating(match.pre_b)} → ${rating(match.post_b)}</span></td>
      <td class="numeric" data-label="Combined pre-match">${rating(match.combined)}</td>
    </tr>`).join("")}</tbody></table></div>`;
  }

  function peakTable(peaks) {
    return `<div class="table-hint" aria-hidden="true">Swipe to see more →</div><div class="table-shell"><table><thead><tr><th class="numeric">Rank</th><th>Nation</th><th class="numeric">Peak NR</th><th>Date</th><th>Peak-making result</th><th class="hide-mobile">Competition</th></tr></thead><tbody>${peaks.map((peak, index) => `<tr>
      <td class="rank-cell numeric">${index + 1}</td><td>${teamLink(peak.code, peak.nation)}</td><td class="numeric"><span class="rating-main">${rating(peak.rating)}</span><span class="rating-sub">strength ${rating(peak.mean)} · uncertainty ${rating(peak.se)}</span></td><td>${validDate(peak.date)}</td><td>${escapeHTML(peak.historical_name)} ${escapeHTML(peak.score)} ${escapeHTML(peak.opponent)}</td><td class="hide-mobile">${escapeHTML(peak.tournament)}</td>
    </tr>`).join("")}</tbody></table></div>`;
  }

  function matchRecordTable(matches) {
    return `<div class="table-hint" aria-hidden="true">Swipe to see more →</div><div class="table-shell"><table><thead><tr><th class="numeric">Rank</th><th>Date</th><th>Match</th><th class="numeric">Score</th><th class="numeric">Combined rating</th><th class="hide-mobile">Competition</th></tr></thead><tbody>${matches.map((match, index) => `<tr>
      <td class="rank-cell numeric">${index + 1}</td><td>${validDate(match.date)}</td><td>${teamLink(match.code1, match.team1)} <span class="muted">v</span> ${teamLink(match.code2, match.team2)}</td><td class="numeric"><span class="score">${escapeHTML(match.score).replace("-", "–")}</span></td><td class="numeric"><span class="rating-main">${rating(match.combined)}</span><span class="rating-sub">combined strength ${rating(match.combined_mean)} · uncertainty ${rating(match.combined_se)}</span></td><td class="hide-mobile">${escapeHTML(match.tournament)}</td>
    </tr>`).join("")}</tbody></table></div>`;
  }

  function upsetTable(matches) {
    return `<div class="table-hint" aria-hidden="true">Swipe to see more →</div><div class="table-shell"><table><thead><tr><th class="numeric">Rank</th><th>Date</th><th>Match</th><th class="numeric">Score</th><th class="numeric">Upset points</th><th>Points won / lost</th><th class="hide-mobile">Competition</th></tr></thead><tbody>${matches.map((match, index) => `<tr>
      <td class="rank-cell numeric">${index + 1}</td><td>${validDate(match.date)}</td><td>${teamLink(match.code1, match.team1)} <span class="muted">v</span> ${teamLink(match.code2, match.team2)}</td><td class="numeric"><span class="score">${escapeHTML(match.score).replace("-", "–")}</span></td><td class="numeric"><span class="rating-main">${rating(match.points)}</span></td><td>${escapeHTML(match.winner)} <b>+${rating(match.winner_gain)}</b><span class="rating-sub">${escapeHTML(match.loser)} −${rating(match.loser_loss)}</span></td><td class="hide-mobile">${escapeHTML(match.tournament)}</td>
    </tr>`).join("")}</tbody></table></div>`;
  }

  function renderRecords(route) {
    setTitle("Records");
    content.innerHTML = `
      <div class="page">
        <header class="page-heading"><div><p class="eyebrow">Historical rating records</p><h1>Records</h1></div><p class="lede">Nation peaks show each country's highest rating. Top matches rank individual fixtures by the combined pre-match rating of both teams. Limited or narrowly connected schedules receive an uncertainty adjustment.</p></header>
        <div class="record-tabs"><button class="button button-dark" data-record="peaks" aria-pressed="true">Nation peaks</button><button class="button" data-record="matches" aria-pressed="false">Top matches</button><button class="button" data-record="upsets" aria-pressed="false">Largest upsets</button></div>
        <div id="record-note" class="record-note"></div>
        <div id="record-table"></div>
        <div class="pagination"><span id="record-count" class="muted small" aria-live="polite"></span><div class="pagination-actions"><button id="record-more" class="button">Show more</button><button id="record-all" class="button button-quiet">Show all</button></div></div>
      </div>`;
    let view = ["peaks", "matches", "upsets"].includes(route.query.get("view")) ? route.query.get("view") : "peaks";
    let shown = Math.max(25, Number(route.query.get("shown") || 25)) || 25;
    document.querySelectorAll("[data-record]").forEach((button) => {
      const active = button.dataset.record === view;
      button.setAttribute("aria-pressed", String(active));
      button.classList.toggle("button-dark", active);
    });
    const update = () => {
      const source = view === "peaks" ? summary.peaks : view === "matches" ? summary.top_matches : summary.upsets;
      const visible = source.slice(0, shown);
      document.getElementById("record-note").innerHTML = view === "peaks"
        ? `<strong>1×</strong><div><b>One maximum per canonical nation.</b> Successor histories are joined; a strict improvement is required to replace the earlier peak.</div>`
        : view === "matches"
          ? `<strong>Q</strong><div><b>Every eligible match instance is ranked.</b> Q is the two breadth-adjusted means minus 1.645 times their joint standard error; repeat pairings are not deduplicated.</div>`
          : `<strong>±</strong><div><b>Decisive results ranked by rating movement.</b> Upset points are the average of the winner's rating gain and the loser's rating loss. The two values can differ because this network-adjusted model is not strictly zero-sum.</div>`;
      document.getElementById("record-table").innerHTML = view === "peaks" ? peakTable(visible) : view === "matches" ? matchRecordTable(visible) : upsetTable(visible);
      document.getElementById("record-count").textContent = `Showing ${number(visible.length)} of ${number(source.length)}`;
      document.getElementById("record-more").hidden = shown >= source.length;
      document.getElementById("record-all").hidden = shown >= source.length;
      replaceRouteQuery("records", { view: view === "peaks" ? "" : view, shown: shown > 25 ? shown : "" });
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
    document.getElementById("record-all").addEventListener("click", () => {
      shown = (view === "peaks" ? summary.peaks : view === "matches" ? summary.top_matches : summary.upsets).length;
      update();
    });
    update();
  }

  async function renderFixtures(route) {
    setTitle("Upcoming matches");
    loading("Loading upcoming internationals…");
    const payload = await getJSON("data/fixtures.json");
    const fixtures = payload.fixtures || [];
    const competitions = [...new Set(fixtures.map((fixture) => fixture.tournament_name))].sort((a, b) => a.localeCompare(b));
    content.innerHTML = `
      <div class="page">
        <header class="page-heading"><div><p class="eyebrow">Scheduled senior internationals</p><h1>Upcoming matches</h1></div><p class="lede">Validated fixtures from multiple public schedules, paired with probabilities from the current ratings. W and L are from the perspective of the first-listed team.</p></header>
        <div class="record-note"><strong>${number(fixtures.length)}</strong><div><b>Known future pairings.</b> Placeholder knockout matches remain hidden until both teams are identified. Feed checked ${validTimestamp(payload.checked_at)}.</div></div>
        <div class="toolbar"><div class="field field-grow"><label for="fixture-search">Team or competition</label><input id="fixture-search" type="search" placeholder="Vietnam, friendly, AFCON…" value="${escapeHTML(route.query.get("q") || "")}"></div><div class="field"><label for="fixture-competition">Competition</label><select id="fixture-competition"><option value="">All competitions</option>${competitions.map((name) => `<option value="${escapeHTML(name)}">${escapeHTML(name)}</option>`).join("")}</select></div></div>
        <p id="fixture-count" class="muted small"></p>
        <div id="fixture-table"></div>
        <div class="pagination"><span id="fixture-page" class="muted small" aria-live="polite"></span><div class="pagination-actions"><button id="fixture-more" class="button">Show more</button><button id="fixture-all" class="button button-quiet">Show all</button></div></div>
      </div>`;
    let shown = Math.max(50, Number(route.query.get("shown") || 50)) || 50;
    const requestedCompetition = route.query.get("competition") || "";
    if (competitions.includes(requestedCompetition)) document.getElementById("fixture-competition").value = requestedCompetition;
    const update = () => {
      const query = document.getElementById("fixture-search").value.trim().toLocaleLowerCase();
      const competition = document.getElementById("fixture-competition").value;
      const filtered = fixtures.filter((fixture) => {
        if (competition && fixture.tournament_name !== competition) return false;
        return !query || `${fixture.team1_name} ${fixture.team2_name} ${fixture.tournament_name}`.toLocaleLowerCase().includes(query);
      });
      const visible = filtered.slice(0, shown);
      document.getElementById("fixture-count").textContent = `${number(filtered.length)} matching fixtures`;
      document.getElementById("fixture-page").textContent = `Showing ${number(visible.length)} of ${number(filtered.length)}`;
      document.getElementById("fixture-more").hidden = visible.length >= filtered.length;
      document.getElementById("fixture-all").hidden = visible.length >= filtered.length;
      document.getElementById("fixture-table").innerHTML = visible.length ? `<div class="table-shell fixture-table"><table><thead><tr><th>Date</th><th>Match</th><th>H/A/N</th><th class="numeric">Combined rating</th><th>W / D / L</th><th class="hide-mobile">Competition</th><th class="hide-mobile">Location</th></tr></thead><tbody>${visible.map((fixture) => `<tr>
        <td>${fixtureDate(fixture)}</td><td data-label="Match">${teamLink(fixture.team1_code, fixture.team1_name)} <span class="muted">v</span> ${teamLink(fixture.team2_code, fixture.team2_name)}<span class="rating-sub">${rating(fixture.rating1)} + ${rating(fixture.rating2)}</span></td><td data-label="Venue">${venueHTML(fixtureSite(fixture))}</td><td class="numeric" data-label="Combined"><span class="rating-main">${rating(fixture.combined_rating)}</span></td><td data-label="Forecast">${probabilityHTML(fixture.probabilities)}</td><td class="hide-mobile" data-label="Competition">${escapeHTML(fixture.tournament_name)}</td><td class="hide-mobile" data-label="Location">${escapeHTML([fixture.city, fixture.country].filter(Boolean).join(", "))}${fixture.neutral ? `<span class="rating-sub">neutral venue</span>` : ""}</td>
      </tr>`).join("")}</tbody></table></div>` : `<div class="empty"><h2>No fixtures match those filters.</h2></div>`;
      replaceRouteQuery("fixtures", { q: document.getElementById("fixture-search").value.trim(), competition, shown: shown > 50 ? shown : "" });
    };
    document.getElementById("fixture-search").addEventListener("input", () => { shown = 50; update(); });
    document.getElementById("fixture-competition").addEventListener("change", () => { shown = 50; update(); });
    document.getElementById("fixture-more").addEventListener("click", () => { shown += 50; update(); });
    document.getElementById("fixture-all").addEventListener("click", () => { shown = fixtures.length; update(); });
    update();
  }

  async function renderPredict() {
    setTitle("Predict a match");
    loading("Loading the current ratings…");
    const state = await getJSON("data/state.json");
    const teams = summary.current;
    const defaultA = teams.find((team) => team.code === "ES") || teams[0];
    const defaultB = teams.find((team) => team.code === "AR") || teams[1];
    const options = (selected) => teams.map((team) => `<option value="${escapeHTML(team.code)}" ${team.code === selected ? "selected" : ""}>${escapeHTML(team.nation)} · ${rating(team.rating)}</option>`).join("");
    content.innerHTML = `
      <div class="page">
        <header class="page-heading"><div><p class="eyebrow">Match probability calculator</p><h1>Predict a match</h1></div><p class="lede">Choose two teams, the venue and whether the match is friendly or competitive. The forecast combines current network strength and uncertainty with each team's recent scoring pattern.</p></header>
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
      const networkProbabilities = powered.map((value) => value / total);
      const [todayYear, todayMonth, todayDay] = todayISO().split("-").map(Number);
      const forecastDay = todayYear * 400 + todayMonth * 32 + todayDay;
      const probabilities = applyForecastLayer(
        networkProbabilities,
        logistic(difference),
        i,
        j,
        matchClass === "friendly",
        Math.max(forecastDay, state.forecast_layer?.as_of_day || forecastDay),
        state.forecast_layer,
      );
      const max = Math.max(...probabilities);
      const jointSE = Math.sqrt(Math.max(0, cov(i, i) + cov(j, j) + 2 * cov(i, j)));
      const combined = teamA.mean + teamB.mean - confidenceZ * jointSE;
      const labels = [`${teamA.nation} win`, "Draw", `${teamB.nation} win`];
      target.innerHTML = `<section class="forecast" aria-live="polite">
        <div class="forecast-title"><div><p class="eyebrow">Match forecast</p><h2>${escapeHTML(teamA.nation)} v ${escapeHTML(teamB.nation)}</h2></div><span>${escapeHTML(matchClass)} · ${home === 0 ? "neutral" : home === 1 ? `${escapeHTML(teamA.nation)} home` : `${escapeHTML(teamB.nation)} home`}</span></div>
        <div class="forecast-bars">${probabilities.map((value, index) => `<div class="forecast-outcome ${value === max ? "is-top" : ""}"><span>${escapeHTML(labels[index])}</span><strong>${percent(value)}</strong></div>`).join("")}</div>
        <div class="forecast-meta"><span>${escapeHTML(teamA.nation)} rating <b>${rating(teamA.rating)}</b></span><span>${escapeHTML(teamB.nation)} rating <b>${rating(teamB.rating)}</b></span><span>Combined rating <b>${rating(combined)}</b></span><span>Rating-gap uncertainty <b>${rating(Math.sqrt(variance))}</b></span></div>
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
        <title id="chart-title">${escapeHTML(nation)} rating history</title><desc id="chart-desc">Rating after each match from ${validDate(history[0].date)} to ${validDate(last.date)}. Peak ${rating(peak.rating)} on ${validDate(peak.date)}.</desc>
        <defs><linearGradient id="rating-gradient" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#ef725f"/><stop offset="1" stop-color="#ef725f" stop-opacity="0"/></linearGradient></defs>
        ${yTicks.map((tick) => `<line class="grid" x1="${pad.left}" y1="${y(tick)}" x2="${width - pad.right}" y2="${y(tick)}"/><text x="${pad.left - 10}" y="${y(tick) + 4}" text-anchor="end">${rating(tick)}</text>`).join("")}
        ${xTicks.map((tick) => `<text x="${x(tick)}" y="${height - 10}" text-anchor="middle">${Math.round(tick)}</text>`).join("")}
        <polygon class="area" points="${area}"/><polyline class="line" points="${line}"/>
        <circle cx="${x(xs[xs.length - 1])}" cy="${y(last.rating)}" r="5" fill="#ef725f"><title>${validDate(last.date)} · ${rating(last.rating)}</title></circle>
      </svg>
      <div class="chart-summary"><span>First eligible: ${validDate(history[0].date)} · ${rating(history[0].rating)}</span><span>Peak: ${validDate(peak.date)} · ${rating(peak.rating)}</span><span>Latest appearance: ${validDate(last.date)} · ${rating(last.rating)}</span></div>
    </div>`;
  }

  async function renderTeam(code, query = new URLSearchParams()) {
    loading("Loading the team history…");
    const page = await getJSON(`data/teams/${encodeURIComponent(code)}.json`);
    const team = page.team;
    const requestedDate = isoDate(query.get("date"));
    const cutoff = requestedDate && requestedDate <= summary.meta.results_through ? requestedDate : "";
    const history = cutoff ? page.history.filter((point) => point.date <= cutoff) : page.history;
    const availableMatches = cutoff ? page.matches.filter((match) => match.date <= cutoff) : page.matches;
    const latestPoint = history.length ? history[history.length - 1] : null;
    const displayName = cutoff && latestPoint?.historical_name ? latestPoint.historical_name : team.nation;
    const historicalStats = availableMatches.reduce((stats, match) => {
      stats.matches += 1;
      stats.gf += match.gf;
      stats.ga += match.ga;
      stats[match.result] += 1;
      return stats;
    }, { matches: 0, gf: 0, ga: 0, W: 0, D: 0, L: 0 });
    const historicalPeak = history.length ? history.reduce((best, point) => point.rating > best.rating ? point : best, history[0]) : null;
    setTitle(displayName);
    content.innerHTML = `
      <div class="page">
        <section class="team-hero">
          <div><p class="eyebrow">${cutoff ? `Historical record through ${validDate(cutoff)}` : team.rank ? `Current world no. ${team.rank}` : "Historical team record"}</p><h1>${escapeHTML(displayName)}</h1>${cutoff && displayName !== team.nation ? `<p class="muted">Part of the continuous ${escapeHTML(team.nation)} rating history</p>` : ""}</div>
          <div class="team-rating"><strong>${rating(cutoff ? latestPoint?.rating : team.rating)}</strong><span>${cutoff && latestPoint ? `after ${validDate(latestPoint.date)} · ` : ""}uncertainty ${rating(cutoff ? latestPoint?.se : team.se)}</span></div>
        </section>
        <div class="team-stats">
          <div><span>Matches</span><strong>${number(cutoff ? historicalStats.matches : team.matches)}</strong></div><div><span>Record</span><strong>${cutoff ? `${historicalStats.W}–${historicalStats.D}–${historicalStats.L}` : `${team.wins}–${team.draws}–${team.losses}`}</strong></div><div><span>Goals</span><strong>${cutoff ? `${historicalStats.gf}–${historicalStats.ga}` : `${team.gf}–${team.ga}`}</strong></div><div><span>${cutoff ? "Latest match" : "Opponent breadth"}</span><strong>${cutoff ? (availableMatches.length ? validDate(availableMatches[0].date) : "—") : number(team.breadth, 1)}</strong></div><div><span>${cutoff ? "Peak by date" : "All-time peak"}</span><strong>${rating(cutoff ? historicalPeak?.rating : team.peak?.rating)}</strong></div>
        </div>
        <section class="section"><div class="section-heading"><div><p class="eyebrow">Rating after each match</p><h2>Rating history${cutoff ? ` to ${validDate(cutoff)}` : ""}</h2></div></div>${ratingChart(history, displayName)}</section>
        <section class="section"><div class="section-heading"><div><p class="eyebrow">${cutoff ? "Matches through selected date" : "Complete match history"}</p><h2>Matches</h2></div><a class="button button-quiet" href="#/matches?team=${encodeURIComponent(team.code)}">Open in explorer →</a></div><div id="team-matches"></div><div class="pagination"><span id="team-count" class="muted small" aria-live="polite"></span><div class="pagination-actions"><button id="team-more" class="button">Show more</button><button id="team-all" class="button button-quiet">Show all</button></div></div></section>
      </div>`;
    let shown = 100;
    const update = () => {
      const matches = availableMatches.slice(0, shown);
      document.getElementById("team-matches").innerHTML = `<div class="table-shell team-match-table"><table><thead><tr><th>Date</th><th>Opponent</th><th>H/A/N</th><th class="numeric">Score</th><th>Result</th><th class="hide-mobile">Competition</th><th>Ratings before → after</th></tr></thead><tbody>${matches.map((match) => `<tr><td data-label="Date">${validDate(match.date)}</td><td data-label="Opponent">${teamLink(match.opponent_code, match.opponent)}</td><td data-label="Venue">${venueHTML(match.site)}</td><td class="numeric" data-label="Score"><span class="score">${match.gf}–${match.ga}</span></td><td data-label="Result">${formHTML([match.result])}</td><td class="hide-mobile" data-label="Competition">${escapeHTML(match.tournament)}</td><td data-label="Ratings"><span class="rating-pair"><b>${escapeHTML(match.team_name)}</b> ${rating(match.pre)} → ${rating(match.post)}</span><span class="rating-pair"><b>${escapeHTML(match.opponent)}</b> ${rating(match.opponent_pre)} → ${rating(match.opponent_post)}</span></td></tr>`).join("")}</tbody></table></div>`;
      document.getElementById("team-count").textContent = `Showing ${number(matches.length)} of ${number(availableMatches.length)}`;
      document.getElementById("team-more").hidden = shown >= availableMatches.length;
      document.getElementById("team-all").hidden = shown >= availableMatches.length;
    };
    document.getElementById("team-more").addEventListener("click", () => { shown += 100; update(); });
    document.getElementById("team-all").addEventListener("click", () => { shown = availableMatches.length; update(); });
    update();
  }

  function renderMethodology() {
    setTitle("Methodology");
    const p = summary.parameters;
    const f = p.forecast_layer;
    content.innerHTML = `
      <article class="page page-narrow prose">
        <p class="eyebrow">How the ratings are calculated</p><h1>Methodology</h1>
        <p class="lede">The system is based on Elo, but it also measures uncertainty, connections between opponents and recent scoring patterns. This page begins with the main ideas, then gives the exact calculations needed to reproduce the ratings and forecasts.</p>

        <div class="method-summary">
          <h2>In plain English</h2>
          <ol>
            <li><b>Start with the teams before the match.</b> Each team has an estimated strength and a level of uncertainty.</li>
            <li><b>Calculate the expected result.</b> The strength difference, venue and historical era determine the expected score.</li>
            <li><b>Check how the teams have been scoring.</b> A separate hidden layer tracks whether each team has recently scored or conceded more than its network strength would suggest.</li>
            <li><b>Combine the two forecasts.</b> The network supplies most of the final probability and the scoring layer makes a smaller correction. If that correction would change the network's most likely result, it is not used for that match.</li>
            <li><b>Compare expectation with reality.</b> An unexpected result creates a larger rating adjustment than an expected one.</li>
            <li><b>Use the winning margin.</b> Larger victories contain more information, but the effect is capped and adjusted for the scoring environment of the era.</li>
            <li><b>Update the opponent network.</b> Shared opponents connect teams, so the model can compare teams that have never met directly.</li>
            <li><b>Allow for uncertainty.</b> The public rating is deliberately cautious when a team's evidence is limited or concentrated within a small group.</li>
          </ol>
          <p><b>The important distinction:</b> the scoring layer changes match probabilities only. It does not change any team's rating, ranking, historical peak or the rating points gained from a result.</p>
        </div>

        <div class="callout"><b>Why use an opponent network?</b> A match tells us the difference between two teams, not either team's absolute strength. Connections through common opponents provide the wider context needed to compare regions and eras. The model keeps track of how certain those comparisons are.</div>

        <h2>1. Expected result</h2>
        <p>First, the model calculates the effective rating gap. For team 1 against team 2, <code>h</code> is +1 when team 1 is at home, −1 when team 2 is at home, and 0 at a neutral venue:</p>
        <div class="formula">δ = a(y)(μ₁ − μ₂) + H(y)h<br>E = 1 / (1 + 10^(−δ/400))</div>
        <p><code>μ</code> is underlying team strength, <code>a(y)</code> controls how strongly a rating gap predicts results in year <code>y</code>, and <code>H(y)</code> is home advantage. <code>E</code> is the expected fractional score: 1 for a win, 0.5 for a draw and 0 for a loss.</p>
        <p>Football and international schedules have changed over time, so the model uses the following era values. Values between the listed years are smoothly interpolated.</p>
        <div class="table-hint" aria-hidden="true">Swipe to see all parameters →</div><div class="table-shell parameter-table"><table><thead><tr><th>Year</th><th class="numeric">Gap scale</th><th class="numeric">Equivalent Elo divisor</th><th class="numeric">Home advantage</th><th class="numeric">Draw chance at equal strength</th></tr></thead><tbody>${p.knot_years.map((year, index) => `<tr><td>${year}${index === 4 ? "+" : ""}</td><td class="numeric">${number(p.calibration_scale[index], 4)}</td><td class="numeric">${number(400 / p.calibration_scale[index], 1)}</td><td class="numeric">${rating(p.home_advantage[index])}</td><td class="numeric">${percent(p.draw_probability[index])}</td></tr>`).join("")}</tbody></table></div>

        <h2>2. Win, draw and loss probabilities</h2>
        <p>The network expected score is first divided into win, draw and loss probabilities. The draw probability is highest when teams are evenly matched and falls as the gap grows:</p>
        <div class="formula">D = pD(y) · 4E(1 − E)<br>W = E − D/2<br>L = 1 − E − D/2</div>
        <p><code>W</code>, <code>D</code> and <code>L</code> are team 1's win, draw and loss probabilities. The calculation integrates the full uncertainty in the strength difference. Its fitted temperature is <b>${number(p.forecast_temperature.friendly, 4)}</b> for friendlies and <b>${number(p.forecast_temperature.competitive, 4)}</b> for competitive matches. Call the resulting vector <code>Pnetwork</code>.</p>

        <h3>Hidden attack and defence layer</h3>
        <p>A second, parallel model tracks attack residual <code>Aᵢ</code> and defence residual <code>Dᵢ</code> for each team. These begin at zero and never enter the published rating. The causal goal baseline uses only matches already played in the current and preceding ${number(f.goal_environment_years)} years, with a ${number(f.goal_prior_matches)}-match prior at ${number(f.goal_prior_per_team, 2)} goals per team:</p>
        <div class="formula">B = [${number(2 * f.goal_prior_matches * f.goal_prior_per_team, 0)} + previous goals] / [${number(2 * f.goal_prior_matches)} + 2(previous matches)]<br>g = ${number(f.parameters.gap_scale, 1)} ln[E/(1−E)]<br>λ₁ = B exp(g/2 + A₁ − D₂)<br>λ₂ = B exp(−g/2 + A₂ − D₁)</div>
        <p>Independent Poisson goal distributions with means <code>λ₁</code> and <code>λ₂</code> are summed into <code>Pscore(W/D/L)</code>. Expected goals are limited to 0.05–8.00. Before a team's next match, its attack and defence residuals are multiplied by <code>exp(−${number(f.parameters.annual_decay, 1)}t)</code>, where <code>t</code> is elapsed years. This gives a half-life of about 2.31 years.</p>
        <p>After the forecast—not before it—the scoring state learns from the result:</p>
        <div class="formula">rᵢ = clip[min(goalsᵢ, ${number(f.parameters.goal_update_cap)}) − λᵢ, −${number(f.parameters.goal_residual_cap)}, +${number(f.parameters.goal_residual_cap)}]<br>Aᵢ′ = Aᵢ + (${number(f.parameters.learning_rate, 2)}/2)rᵢ<br>Dⱼ′ = Dⱼ − (${number(f.parameters.learning_rate, 2)}/2)rᵢ</div>
        <p>The same mirrored update is made for the opponent's goals. Friendlies and competitive matches update this hidden scoring state equally; testing did not support a separate friendly learning rate.</p>

        <h3>Annual calibration, blend and safety rule</h3>
        <p>At the start of each calendar year, the score probabilities and blend weight are refitted using only the preceding ${number(f.calibration_window_years)} complete calendar years. For ${number(f.calibration.year)}, that means ${number(f.calibration.training_matches)} matches from ${number(f.calibration.training_first_year)}–${number(f.calibration.training_last_year)}. The current score calibration uses draw log tilt <b>${number(f.calibration.draw_log_tilt, 4)}</b>, friendly power <b>${number(f.calibration.friendly_temperature, 4)}</b> and competitive power <b>${number(f.calibration.competitive_temperature, 4)}</b>.</p>
        <div class="formula">Ppool = ${number(f.calibration.nfelo_weight, 4)} Pnetwork + ${number(f.calibration.score_weight, 4)} Pscore<br>Pfinal = Ppool, if argmax(Ppool) = argmax(Pnetwork)<br>Pfinal = Pnetwork, otherwise</div>
        <p>The complete network vector is therefore restored whenever the blend would change the network's most-likely win/draw/loss call. This guarantees that the probability layer cannot lower the model's recorded top-outcome accuracy. The structural values are frozen; only the scheduled annual calibration is refitted by the published rule.</p>

        <h2>3. Winning margin</h2>
        <p>A 4–0 result is stronger evidence than a 1–0 result, but four times the margin should not produce four times the rating change. The margin is capped at seven goals and compared with decisive matches in the preceding 20 years. This prevents high-scoring eras from receiving unfairly large adjustments.</p>
        <div class="formula">C(y) = [20·1.10 + Σ(min(mᵣ,7)−1)] / (20 + N)<br>m* = min[7, 1 + (min(m,7)−1)(1.10/max(0.10,C))^${number(p.goal_margin.environment_power, 10)}]</div>
        <p>After this adjustment, the information weights are: draw <b>${number(p.goal_margin.draw, 3)}</b>, one-goal win <b>1.000</b>, two-goal win <b>${number(p.goal_margin.two, 3)}</b>, three-goal win <b>${number(p.goal_margin.three, 3)}</b>, and <b>${number(p.goal_margin.tail, 3)}</b> more for each additional effective goal.</p>

        <h2>4. Updating team strength and uncertainty</h2>
        <p>The model stores all team strengths in <code>μ</code> and their joint uncertainty in <code>Σ</code>. Before a team plays, its uncertainty increases slightly according to the time since its previous match. A new team begins with standard deviation <b>${rating(p.network.prior_sd)}</b>. For the match, let <code>x=e₁−e₂</code>, <code>v=Σx</code>, <code>V=xᵀΣx</code>, <code>β=a(y)ln(10)/400</code>, and <code>λ=${number(p.network.quality_scale, 6)}G(m)</code>.</p>
        <div class="formula">d = 1 + λβ²E(1−E)V<br>μ′ = μ + v · λβ(S−E)/d<br>Σ′ = Σ − vvᵀ · λβ²E(1−E)/d</div>
        <p><code>S</code> is the actual fractional score and <code>G(m)</code> is the margin weight. The mean update is larger when a result is surprising and informative. The uncertainty update reflects how much the match taught us. Every result receives the same network-rating evidence weight; match class affects probability calibration, not the rating update.</p>

        <h2>5. New teams and successor histories</h2>
        <p>A new team starts near the median strength of active, established teams rather than at an arbitrary fixed rating. The starting value also adjusts modestly for the size of the active international pool:</p>
        <div class="formula">μdebut = median(active pool) ${p.debut.offset < 0 ? "−" : "+"} ${number(Math.abs(p.debut.offset), 10)} ${p.debut.pool_slope < 0 ? "−" : "+"} ${number(Math.abs(p.debut.pool_slope), 10)} ln[(A+10)/50]</div>
        <p>Historical names that represent the same continuing national side are joined into one successor history. Separate national teams are not merged merely because they share geography or political ancestry.</p>

        <h2>6. The rating shown on the site</h2>
        <p>The public ranking is calculated only from the opponent-network strength and uncertainty—not from the hidden scoring layer. It uses a cautious presentation so that teams with a narrow or poorly connected schedule do not appear artificially high. Recent opponents receive more weight, with an eight-year half-life. The effective number of distinct opponents gives breadth reliability <code>ρ=N/(N+4)</code>. <code>B</code> is the average underlying strength of the active top ten.</p>
        <div class="formula">Mᵢ = 2000 + ρᵢ(μᵢ − B)<br>NRᵢ = Mᵢ − 1.64485362695 √Σᵢᵢ<br>Qᵢⱼ = Mᵢ + Mⱼ − 1.64485362695 √(Σᵢᵢ+Σⱼⱼ+2Σᵢⱼ)</div>
        <p><code>M</code> is breadth-adjusted strength, <code>NR</code> is the displayed team rating, and <code>Q</code> is the combined rating of a matchup. The subtraction of 1.645 standard errors is a conservative uncertainty allowance. A historical peak or matchup enters the records after both teams have at least 30 earlier matches.</p>

        <h2>7. How the model was tested</h2>
        <p>Testing used rolling historical cut-offs: score-state parameters were chosen using earlier matches, annual calibration used only the preceding eight complete years, and forecasts were evaluated on later matches. This produced ${number(summary.validation.matches)} pre-match predictions from 1960 to 2026. The outcome-preserving layer improved every one of the five chronological test blocks.</p>
        <div class="metric-grid"><div><span>Log loss</span><strong>${number(summary.validation.log_loss, 4)}</strong></div><div><span>Brier score</span><strong>${number(summary.validation.brier, 4)}</strong></div><div><span>Ranked probability score</span><strong>${number(summary.validation.rps, 4)}</strong></div><div><span>Most likely outcome correct</span><strong>${percent(summary.validation.accuracy)}</strong></div></div>
        <p>Lower values are better for the first three measures. Log loss is primary because it rewards accurate probabilities and strongly penalises unjustified certainty. Network-only NFELO scored <b>${number(summary.validation.network_only_log_loss, 4)}</b>; the final layer scored <b>${number(summary.validation.log_loss, 4)}</b>, with a paired year-cluster 95% difference interval of <b>${number(summary.validation.log_loss_difference_low_95, 4)}</b> to <b>${number(summary.validation.log_loss_difference_high_95, 4)}</b>. Both made exactly the same most-likely-result calls by construction. The comparison World Football Elo forecast scored <b>${number(summary.validation.published_wfe_log_loss, 4)}</b>.</p>

        <h2>8. Important limitations</h2>
        <p>The model uses match results, score, date, venue and competition type. It does not know the selected squad, injuries, red cards, travel, rest, tactics, weather or betting-market information. The probability improvement is statistically supported but small; ratings and probabilities remain estimates, not certainties or betting advice.</p>
      </article>`;
  }

  function renderAbout() {
    setTitle("About and updates");
    const update = summary.meta.source_update || {};
    content.innerHTML = `
      <div class="page page-narrow">
        <p class="eyebrow">Data · updates · limitations</p><h1>About</h1>
        <p class="lede">Network Football Elo is an independent international football rating and prediction system. It covers senior men's internationals from 1872 to the present.</p>
        <section class="section split">
          <div class="panel"><p class="eyebrow">Results included through</p><h2>${validDate(summary.meta.results_through)}</h2><p>${number(summary.meta.matches)} matches across ${number(summary.meta.teams)} team histories.</p><p class="muted small">Data checked: ${update.source_checked_at ? validTimestamp(update.source_checked_at) : validDate(summary.meta.results_through)}<br>Site generated: ${validTimestamp(summary.meta.generated_at)}</p></div>
          <div class="panel panel-dark"><p class="eyebrow">Automatic updates</p><h2>Checked three times daily.</h2><p class="muted">Results and fixtures are checked after the main Americas, Asia/Oceania and Europe/Africa match windows. Each update is validated and the complete rating history is rebuilt before publication. If new data fails validation, the existing site remains online unchanged.</p></div>
        </section>
        <article class="section prose">
          <h2>Data sources</h2>
          <p>Historical results and team labels are based on <a href="https://eloratings.net/" rel="external">World Football Elo Ratings</a>. Recent results use the CC0-licensed <a href="https://github.com/martj42/international_results" rel="external">international_results dataset</a> and the public-domain <a href="https://github.com/openfootball/worldcup.json" rel="external">OpenFootball World Cup feed</a>. Future fixtures use World Football Elo Ratings' cross-confederation schedule, supplemented by <a href="https://www.thesportsdb.com/" rel="external">TheSportsDB</a> for richer competition details. Duplicate events are merged and conflicting scores stop publication.</p>
          <h2>Automatic updates</h2>
          <p>When new results arrive, the entire history is recalculated in chronological order. This matters because each rating and hidden scoring state depends on earlier results. Rating parameters and forecast-layer structure remain fixed during routine updates. Once each January, probability calibration is automatically refitted from the preceding eight complete calendar years under the published rule; this scheduled calculation does not alter ratings or rankings.</p>
          <h2>What the model does not know</h2>
          <p>It does not use line-ups, player availability, injuries, red cards, travel, rest, tactical matchups, weather or betting markets. Its probabilities describe the historical-information model, not certainty and not a recommendation to wager.</p>
          <h2>Quality checks</h2>
          <p>Every update checks the source format, row count, dates, scores and team names. The site is published only after the ratings are rebuilt and automated consistency tests pass.</p>
        </article>
      </div>`;
  }

  function renderNotFound() {
    setTitle("Not found");
    content.innerHTML = `<div class="error-panel"><p class="eyebrow">404</p><h2>Page not found</h2><p>Return to the current rankings or explore the match history.</p><a class="button button-dark" href="#/">Go home</a></div>`;
  }

  async function route() {
    const current = parseRoute();
    setActiveNav(current.section);
    try {
      if (!summary) [summary, catalog] = await Promise.all([getJSON("data/summary.json"), getJSON("data/catalog.json")]);
      switch (current.section) {
        case "home": await renderHome(); break;
        case "rankings": renderRankings(current); break;
        case "history": await renderHistory(current); break;
        case "matches": await renderMatches(current); break;
        case "fixtures": await renderFixtures(current); break;
        case "records": renderRecords(current); break;
        case "predict": await renderPredict(); break;
        case "team": current.value ? await renderTeam(current.value, current.query) : renderNotFound(); break;
        case "methodology": renderMethodology(); break;
        case "about": renderAbout(); break;
        default: renderNotFound();
      }
      setRouteMetadata(current);
      if (location.hash.startsWith("#/")) history.replaceState(null, "", cleanRouteURL(current.section, current.value, current.query));
      content.focus({ preventScroll: true });
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
  document.addEventListener("click", (event) => {
    if (nav.classList.contains("is-open") && !nav.contains(event.target) && event.target !== menuButton) {
      nav.classList.remove("is-open");
      menuButton.setAttribute("aria-expanded", "false");
    }
  });
  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape" && nav.classList.contains("is-open")) {
      nav.classList.remove("is-open");
      menuButton.setAttribute("aria-expanded", "false");
      menuButton.focus();
    }
  });
  window.addEventListener("hashchange", route);
  route();
})();
