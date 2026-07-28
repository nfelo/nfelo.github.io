(function () {
  "use strict";

  window.__nfeloBoot = window.__nfeloBoot || {};
  if (window.__nfeloBoot.started) return;
  window.__nfeloBoot.started = true;

  const content = document.getElementById("content");
  const nav = document.getElementById("site-nav");
  const menuButton = document.querySelector(".menu-button");
  const dataCache = new Map();
  const confidenceZ = 1.6448536269514715;
  let summary;
  let catalog;
  let teamAliasSearch = new Map();


  const publicTeamName = (value) => (
    String(value ?? "") === "USSR"
      ? "Soviet Union"
      : String(value ?? "")
  );
  const foldSearch = (value) => (
    publicTeamName(value)
      .normalize("NFKD")
      .replace(/[\u0300-\u036f]/g, "")
      .toLocaleLowerCase()
      .replace(/\s+/g, " ")
      .trim()
  );
  const shuffledExamples = (values, limit = 3) => {
    const names = [
      ...new Set(
        values
          .map(publicTeamName)
          .map((value) => value.trim())
          .filter(Boolean),
      ),
    ];
    for (
      let index = names.length - 1;
      index > 0;
      index -= 1
    ) {
      const swapIndex = Math.floor(
        Math.random() * (index + 1),
      );
      [names[index], names[swapIndex]] = [
        names[swapIndex],
        names[index],
      ];
    }
    const examples = names.slice(
      0,
      Math.min(limit, names.length),
    );
    return examples.length
      ? (
        examples.join(", ")
        + (examples.length < names.length ? "…" : "")
      )
      : "";
  };

const PUBLIC_LINEAGE_COMPLETIONS = [
  ["Serbia", "Serbia and Montenegro", "Yugoslavia"],
];
const completePublicLineageNames = (values) => {
  const names = [
    ...new Set(
      values
        .map(publicTeamName)
        .map((value) => String(value).trim())
        .filter(Boolean),
    ),
  ];
  const folded = new Set(names.map(foldSearch));
  PUBLIC_LINEAGE_COMPLETIONS.forEach((group) => {
    if (group.some((name) => folded.has(foldSearch(name)))) {
      group.forEach((name) => {
        const publicName = publicTeamName(name);
        if (!names.includes(publicName)) names.push(publicName);
      });
    }
  });
  return names;
};
const formatPublicNameList = (values) => {
  const names = completePublicLineageNames(values);
  if (names.length < 2) return names[0] || "";
  if (names.length === 2) return names.join(" and ");
  return `${names.slice(0, -1).join(", ")}, and ${names.at(-1)}`;
};
const filteredEmptyState = (subject) => (
  `<div class="empty"><h2>No ${subject} match these filters.</h2>`
  + "<p>Change or clear the filters to see results.</p></div>"
);

  const initialiseTeamAliasSearch = () => {
    teamAliasSearch = new Map(
      summary.teams.map((team) => [
        team.code,
        foldSearch(
          [
            team.nation,
            ...(team.aliases || []),
            team.code,
          ].join(" "),
        ),
      ]),
    );
  };
  const teamSearchText = (code, ...names) => (
    foldSearch(
      [
        teamAliasSearch.get(code) || "",
        ...names.map(publicTeamName),
      ].join(" "),
    )
  );

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
  const yearNumber = (value) => Number(value).toLocaleString("en", { useGrouping: false });
  const rating = (value) => value == null ? "—" : Number(value).toLocaleString("en", {
    minimumFractionDigits: 1,
    maximumFractionDigits: 1,
    useGrouping: false,
  });
  const signedRating = (value) => (
    value == null
      ? "—"
      : `${Number(value) >= 0 ? "+" : "−"}${rating(Math.abs(Number(value)))}`
  );
  const percent = (value) => `${number(value * 100, 1)}%`;
  const precisePercent = (value) => `${number(value * 100, 3)}%`;
  const signedPercent = (value) => (
    value == null
      ? "—"
      : `${Number(value) >= 0 ? "+" : "−"}${number(Math.abs(Number(value)) * 100, 1)}%`
  );
  const todayISO = () => {
    const today = new Date();
    return `${today.getFullYear()}-${String(today.getMonth() + 1).padStart(2, "0")}-${String(today.getDate()).padStart(2, "0")}`;
  };
  const modelDayNumber = (value) => {
    const match = String(value || "").match(/^(\d{4})-(\d{2})-(\d{2})$/);
    if (!match) return null;
    return Number(match[1]) * 400 + Number(match[2]) * 32 + Number(match[3]);
  };
  const projectVenueProfile = (profile, targetDay) => {
    if (!profile || targetDay == null) return null;
    const parameters = summary?.parameters?.venue_effects;
    const prior = Number(parameters?.prior_sd);
    const halfLife = Number(parameters?.half_life_years);
    const sourceDay = Number(profile.as_of_day);
    const dependence = Number(profile.dependence);
    const standardError = Number(profile.se);
    if (
      !Number.isFinite(prior)
      || !Number.isFinite(halfLife)
      || !Number.isFinite(sourceDay)
      || !Number.isFinite(dependence)
      || !Number.isFinite(standardError)
    ) {
      return null;
    }
    const elapsed = Math.max(0, (targetDay - sourceDay) / 400);
    const retention = Math.pow(0.5, elapsed / halfLife);
    const variance = Math.max(
      0,
      prior * prior
      - (prior * prior - standardError * standardError)
        * retention * retention,
    );
    const projected = dependence * retention;
    const homeShare = Number(parameters.home_share);
    const awayShare = Number(parameters.away_share);
    return {
      dependence: projected,
      se: Math.sqrt(variance),
      hosting_adjustment: homeShare * projected,
      away_adjustment: -awayShare * projected,
      away_disadvantage: awayShare * projected,
      neutral: Number(parameters.neutral_effect),
      reliability: Math.max(
        0,
        Math.min(1, 1 - variance / (prior * prior)),
      ),
      matches: Number(profile.matches) || 0,
      as_of_day: targetDay,
    };
  };
  const venueProfileFromState = (state, index, targetDay) => {
    const venue = state?.venue_effects;
    if (!venue || index == null) return null;
    return projectVenueProfile({
      dependence: Number(venue.means[index]),
      se: Math.sqrt(Math.max(0, Number(venue.variances[index]))),
      matches: Number(venue.matches[index]),
      as_of_day: Number(venue.last_day[index]),
    }, targetDay);
  };
  const projectScoreProfile = (profile, targetDay) => {
    if (!profile || targetDay == null) return null;
    const sourceDay = Number(profile.last_day);
    const annualDecay = Number(profile.annual_decay);
    const attack = Number(profile.attack);
    const defence = Number(profile.defence);
    if (
      !Number.isFinite(sourceDay)
      || sourceDay < 0
      || !Number.isFinite(annualDecay)
      || annualDecay <= 0
      || !Number.isFinite(attack)
      || !Number.isFinite(defence)
    ) {
      return null;
    }
    const elapsed = Math.max(0, (targetDay - sourceDay) / 400);
    const retention = Math.exp(-annualDecay * elapsed);
    const projectedAttack = attack * retention;
    const projectedDefence = defence * retention;
    return {
      attack: projectedAttack,
      defence: projectedDefence,
      attack_goal_change: Math.exp(projectedAttack) - 1,
      opponent_goal_change: Math.exp(-projectedDefence) - 1,
      last_day: sourceDay,
      annual_decay: annualDecay,
      learning_rate: Number(profile.learning_rate),
      release: String(profile.release || ""),
    };
  };
  const compactVenueProfileHTML = (profile) => (
    profile
      ? `<span class="venue-summary"><b>${signedRating(profile.dependence)}</b><small>host ${signedRating(profile.hosting_adjustment)} · away ${signedRating(profile.away_adjustment)}</small></span>`
      : "—"
  );
  const projectTeamRating = (team, asOfDate) => {
    const sourceDate = team?.rating_date || team?.date;
    const sourceDay = modelDayNumber(sourceDate);
    const targetDay = modelDayNumber(asOfDate);
    const standardError = Number(team?.se);
    const mean = Number(team?.mean);
    const drift = Number(summary?.parameters?.network?.drift_sd);
    if (
      sourceDay == null
      || targetDay == null
      || !Number.isFinite(standardError)
      || !Number.isFinite(mean)
      || !Number.isFinite(drift)
    ) {
      return { ...team };
    }
    const elapsed = Math.max(0, (targetDay - sourceDay) / 400);
    const se = Math.sqrt(standardError * standardError + drift * drift * elapsed);
    return {
      ...team,
      rating: mean - confidenceZ * se,
      se,
      rating_date: asOfDate,
    };
  };
  const currentRankingForDate = (state, asOfDate) => {
    const year = Number(asOfDate.slice(0, 4));
    const targetDay = modelDayNumber(asOfDate);
    const codeIndex = new Map(
      state.codes.map((code, index) => [code, index]),
    );
    const reference = summary.teams
      .filter((team) => (
        team.matches >= 30
        && year - Number(team.last_year) <= 8
      ))
      .sort((first, second) => (
        Number(state.means[codeIndex.get(second.code)])
        - Number(state.means[codeIndex.get(first.code)])
      ))
      .slice(0, 10);
    if (reference.length < 2) return [];
    const baseline = reference.reduce(
      (total, team) => (
        total + Number(state.means[codeIndex.get(team.code)])
      ),
      0,
    ) / reference.length;
    const count = state.codes.length;
    const drift = Number(summary.parameters.network.drift_sd);
    const ranked = summary.teams
      .filter((team) => (
        team.matches >= 30
        && year - Number(team.last_year) <= 4
      ))
      .map((team) => {
        const index = codeIndex.get(team.code);
        const elapsed = Math.max(
          0,
          (targetDay - Number(state.last_day[index])) / 400,
        );
        const variance = Math.max(
          0,
          Number(state.covariance[index * count + index])
          + drift * drift * elapsed,
        );
        const se = Math.sqrt(variance);
        const mean = (
          2000
          + Number(team.reliability)
          * (Number(state.means[index]) - baseline)
        );
        return {
          ...team,
          rating: mean - confidenceZ * se,
          mean,
          se,
          latent: 1500 + Number(state.means[index]),
          rating_date: asOfDate,
        };
      })
      .sort((first, second) => (
        second.rating - first.rating
        || first.nation.localeCompare(second.nation)
      ));
    ranked.forEach((team, index) => {
      team.rank = index + 1;
    });
    return ranked;
  };
  const previousISODate = (value) => {
    const parsed = new Date(`${value}T00:00:00Z`);
    if (
      Number.isNaN(parsed.valueOf())
      || parsed.toISOString().slice(0, 10) !== value
    ) {
      return "";
    }
    parsed.setUTCDate(parsed.getUTCDate() - 1);
    return parsed.toISOString().slice(0, 10);
  };
  const predictURL = ({
    date,
    first,
    second,
    venue = 0,
    matchClass = "competitive",
    matchId = null,
  }) => {
    const query = new URLSearchParams({
      date,
      a: first,
      b: second,
      venue: String(venue),
      "class": (
        matchClass === "friendly"
          ? "friendly"
          : "competitive"
      ),
    });
    if (matchId != null) {
      query.set("match", String(matchId));
    }
    return `#/predict?${query.toString()}`;
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
  const teamLink = (code, name, date = "") => `<a class="team-link" href="${teamURL(code, date)}">${escapeHTML(publicTeamName(name))}</a>`;
  const cleanRouteURL = (section, value = "", query = new URLSearchParams()) => {
    const path = [section === "home" ? "" : section, value].filter(Boolean).map(encodeURIComponent).join("/");
    const suffix = query.toString();
    return `${new URL(path ? `${path}/` : "", document.baseURI).pathname}${suffix ? `?${suffix}` : ""}`;
  };
  const currentScrollY = () => (
    Number.isFinite(Number(window.scrollY))
      ? Math.max(0, Number(window.scrollY))
      : 0
  );
  const routeHistoryState = (scrollY = currentScrollY()) => ({
    ...(
      history.state && typeof history.state === "object"
        ? history.state
        : {}
    ),
    nfeloRoute: true,
    nfeloScrollY: scrollY,
  });
  const replaceRouteQuery = (section, values) => {
    const query = new URLSearchParams();
    Object.entries(values).forEach(([key, value]) => { if (value !== "" && value != null) query.set(key, value); });
    history.replaceState(
      routeHistoryState(),
      "",
      cleanRouteURL(section, "", query),
    );
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
      tournaments: "Compare participating teams immediately before and after international tournaments.",
      matches: "Search international football results and pre-match forecasts from 1872 onward.",
      fixtures: "Upcoming senior internationals with current ratings and match probabilities.",
      records: "Team peaks, number-one records, highest-rated matches, largest upsets and tournament rating gains.",
      compare: "Compare up to ten current or historical national teams, then inspect any selected head-to-head pairing.",
      predict: "Predict historical or current matchups with W/D/L, exact-score and rating-impact tables.",
      methodology: "Detailed, reproducible methodology for the Network Football Elo model.",
      faq: "Clear answers about Network Football Elo ratings, forecasts, tournaments, records, data and methodology.",
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

  function routeFromInternalHref(href) {
    if (!String(href || "").startsWith("#/")) return null;
    const [path, query = ""] = String(href).slice(2).split("?");
    const parts = path
      .split("/")
      .filter(Boolean)
      .map(decodeURIComponent);
    return {
      section: parts[0] || "home",
      value: parts[1] || "",
      query: new URLSearchParams(query),
    };
  }

  function navigateToInternalRoute(target) {
    const destination = cleanRouteURL(
      target.section,
      target.value,
      target.query,
    );
    const current = `${location.pathname}${location.search}`;
    if (!location.hash && destination === current) {
      route({ scrollMode: "top" });
      return;
    }
    history.replaceState(routeHistoryState(), "");
    history.pushState(
      {
        nfeloRoute: true,
        nfeloScrollY: 0,
      },
      "",
      destination,
    );
    route({ scrollMode: "top" });
  }

  function closeNavigation(focusMenu = false) {
    const menuWasOpen = Boolean(nav?.classList.contains("is-open"));
    nav?.classList.remove("is-open");
    nav?.querySelectorAll(".nav-group[open]").forEach((group) => {
      group.removeAttribute("open");
    });
    menuButton?.setAttribute("aria-expanded", "false");
    if (focusMenu && menuWasOpen) menuButton?.focus();
  }

  function setActiveNav(section) {
    nav?.querySelectorAll("a").forEach((link) => {
      const target = link.getAttribute("href")?.replace("#/", "").split("?")[0];
      if (target === section) link.setAttribute("aria-current", "page");
      else link.removeAttribute("aria-current");
    });
    nav?.querySelectorAll(".nav-group").forEach((group) => {
      group.classList.toggle(
        "contains-current",
        Boolean(group.querySelector('[aria-current="page"]')),
      );
    });
    closeNavigation();
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
  const formatHistoryDateInput = (value) => {
    const digits = String(value).replace(/\D/g, "").slice(0, 8);
    if (digits.length <= 2) return digits;
    if (digits.length <= 4) return `${digits.slice(0, 2)}/${digits.slice(2)}`;
    return `${digits.slice(0, 2)}/${digits.slice(2, 4)}/${digits.slice(4)}`;
  };
  const historyDateInputError = (value, firstDate, lastDate) => {
    const digits = String(value).replace(/\D/g, "").slice(0, 8);
    if (digits.length && Number(digits[0]) > 3) return "Day must be between 01 and 31.";
    if (digits.length >= 2 && (Number(digits.slice(0, 2)) < 1 || Number(digits.slice(0, 2)) > 31)) return "Day must be between 01 and 31.";
    if (digits.length >= 3 && Number(digits[2]) > 1) return "Month must be between 01 and 12.";
    if (digits.length >= 4 && (Number(digits.slice(2, 4)) < 1 || Number(digits.slice(2, 4)) > 12)) return "Month must be between 01 and 12.";
    if (digits.length < 8) return "";
    const chosen = inputDate(formatHistoryDateInput(digits));
    if (!chosen) return "Enter a real calendar date as DD/MM/YYYY.";
    if (chosen < firstDate || chosen > lastDate) return `Choose a date from ${validDate(firstDate)} to ${validDate(lastDate)}.`;
    return "";
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

  function probabilityHTML(values, prediction = null) {
    const labels = ["W", "D", "L"];
    const classes = ["pw", "pd", "pl"];
    const bar = `<div class="probability" aria-label="Win ${percent(values[0])}, draw ${percent(values[1])}, loss ${percent(values[2])}">${values.map((value, index) => `<span class="${classes[index]}" style="width:${Math.max(12, value * 100)}%" title="${labels[index]} ${percent(value)}">${number(value * 100, 0)}</span>`).join("")}</div>`;
    if (
      !prediction?.date
      || !prediction.first
      || !prediction.second
    ) {
      return bar;
    }
    const label = (
      prediction.label
      || "Open the full match prediction"
    );
    return `<a class="probability-link" href="${predictURL(prediction)}" title="Open full prediction" aria-label="${escapeHTML(label)}">${bar}</a>`;
  }

  function ratingForecastExplanation() {
    return `<div class="callout forecast-explanation"><b>Why can the lower-rated team be the forecast favourite?</b> The public rating is deliberately reduced for limited opponent breadth and uncertainty so rankings remain cautious and comparable across eras. Match probabilities use the model's underlying strength estimate, its uncertainty, the two countries’ time-varying home/away profiles and team-specific attack and defence tendencies. The two outputs therefore answer related but different questions. <a href="#/methodology?section=ratings">How ratings and forecasts fit together →</a></div>`;
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

  function boundaryPool(base, candidate) {
    const winner = base.indexOf(Math.max(...base));
    const candidateWinner = candidate.indexOf(Math.max(...candidate));
    if (winner === candidateWinner) return candidate;
    const delta = candidate.map((value, index) => value - base[index]);
    let fraction = 1;
    delta.forEach((_, competitor) => {
      if (competitor === winner) return;
      const closing = delta[competitor] - delta[winner];
      if (closing > 0) {
        fraction = Math.min(
          fraction,
          (base[winner] - base[competitor]) / closing,
        );
      }
    });
    fraction = Math.max(0, Math.min(1, fraction * (1 - 1e-10)));
    const result = base.map((value, index) => value + fraction * delta[index]);
    const total = result.reduce((sum, value) => sum + value, 0);
    return result.map((value) => value / total);
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
    return boundaryPool(base, pooled);
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
            <a class="button button-primary home-action home-action-rankings" href="#/rankings">See the rankings</a>
            <a class="button home-action home-action-fixtures" href="#/fixtures">Upcoming matches</a>
            <a class="button home-action home-action-predict" href="#/predict">Predict any historical or current matchup</a>
          </div>
          </div>
          <dl class="home-facts">
            <div><dt>Latest result</dt><dd>${validDate(summary.meta.results_through)}</dd></div>
            <div><dt>Matches</dt><dd>${number(summary.meta.matches)}</dd></div>
            <div><dt>Teams</dt><dd>${number(summary.meta.teams)}</dd></div>
            <div class="home-accuracy"><dt>Top-choice W/D/L accuracy</dt><dd>${percent(summary.validation.retrospective.accuracy)}</dd></div>
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
            <div class="home-help-links">
              <a href="#/methodology?section=strength">How the network works →</a>
              <a href="#/faq">Questions? Read the FAQ →</a>
            </div>
          </div>
          <div class="home-records">
            <div class="compact-heading"><div><p class="eyebrow">Record book</p><h2>Highest-rated matches</h2></div><a href="#/records">All records →</a></div>
            <ol>${summary.top_matches.slice(0, 5).map((match, index) => `<li><span>${index + 1}</span><div>${teamLink(match.code1, match.team1)} <i>v</i> ${teamLink(match.code2, match.team2)}<small>${validDate(match.date)}</small></div><strong>${rating(match.combined)}</strong></li>`).join("")}</ol>
          </div>
        </section>

      <nav class="home-explore" aria-labelledby="home-explore-title">
        <div class="compact-heading">
          <div>
            <p class="eyebrow">More ways to explore</p>
            <h2 id="home-explore-title">Explore</h2>
          </div>
        </div>
        <div class="home-explore-links">
          <a href="#/history"><b>Historical rankings</b><span>Choose any completed matchday.</span></a>
          <a href="#/tournaments"><b>Tournaments</b><span>Compare every participant before or after an edition.</span></a>
          <a href="#/records"><b>Records</b><span>Peaks, No. 1 totals, matches, upsets and tournament gains.</span></a>
          <a href="#/compare"><b>Compare teams</b><span>Ratings, histories and head-to-head results.</span></a>
        </div>
      </nav>
      </div>`;
  }

  function movementHTML(team) {
    if (team.rating_change_12m == null) return `<span class="muted">Not ranked</span>`;
    const rankChange = team.rank_change_12m;
    const ratingChange = team.rating_change_12m;
    const direction = rankChange > 0 || (rankChange === 0 && ratingChange > 0)
      ? "movement-up"
      : rankChange < 0 || (rankChange === 0 && ratingChange < 0)
        ? "movement-down"
        : "movement-flat";
    const arrow = rankChange > 0 ? "▲" : rankChange < 0 ? "▼" : "•";
    const rankLabel = rankChange == null
      ? "No comparable rank"
      : rankChange === 0
        ? "No rank change"
        : `${Math.abs(rankChange)} place${Math.abs(rankChange) === 1 ? "" : "s"} ${rankChange > 0 ? "up" : "down"}`;
    return `<span class="movement ${direction}" title="Since ${validDate(team.movement_date_12m)}: ${rankLabel}; rating ${ratingChange >= 0 ? "+" : ""}${rating(ratingChange)}"><b>${arrow} ${rankChange == null ? "—" : Math.abs(rankChange)}</b><small>${ratingChange >= 0 ? "+" : ""}${rating(ratingChange)} pts</small></span>`;
  }

  function rankingsTable(items, showRank) {
    if (!items.length) return filteredEmptyState("teams");
    const rankValue = (team, index) => (
      showRank
        ? team.display_rank ?? team.rank ?? index + 1
        : index + 1
    );
    return `<div class="ranking-desktop"><div class="table-shell"><table class="ranking-table">
      <thead><tr><th class="numeric">Rank</th><th>Team</th><th class="numeric">Rating</th><th class="numeric">12-month change</th><th class="numeric hide-mobile">Underlying strength estimate</th><th class="numeric hide-mobile">Matches</th><th>Recent form</th><th class="hide-mobile">All-time peak</th></tr></thead>
      <tbody>${items.map((team, index) => `<tr>
        <td class="rank-cell numeric">${rankValue(team, index)}</td>
        <td>${teamLink(team.code, team.nation)}</td>
        <td class="numeric"><span class="rating-main">${rating(team.rating)}</span><span class="rating-sub">uncertainty ${rating(team.se)}</span></td>
        <td class="numeric">${movementHTML(team)}</td>
        <td class="numeric hide-mobile">${rating(team.mean)}</td>
        <td class="numeric hide-mobile">${number(team.matches)}</td>
        <td>${formHTML(team.form || [])}</td>
        <td class="hide-mobile">${team.peak ? `${rating(team.peak.rating)} · ${validDate(team.peak.date)}` : "—"}</td>
      </tr>`).join("")}</tbody>
    </table></div></div>
    <ol class="ranking-cards" aria-label="Rankings">
      ${items.map((team, index) => `<li class="ranking-card">
        <div class="ranking-card-heading">
          <span class="ranking-card-rank">No. ${rankValue(team, index)}</span>
          <div class="ranking-card-rating"><strong>${rating(team.rating)}</strong><small>uncertainty ${rating(team.se)}</small></div>
        </div>
        <div class="ranking-card-team">${teamLink(team.code, team.nation)}</div>
        <div class="ranking-card-snapshot">
          <div><span>12-month change</span>${movementHTML(team)}</div>
          <div><span>Recent form</span>${formHTML(team.form || [])}</div>
        </div>
        <details class="ranking-card-details">
          <summary>More ranking details</summary>
          <dl>
            <div><dt>Underlying strength estimate</dt><dd>${rating(team.mean)}</dd></div>
            <div><dt>Matches</dt><dd>${number(team.matches)}</dd></div>
            <div><dt>All-time peak</dt><dd>${team.peak ? `${rating(team.peak.rating)} · ${validDate(team.peak.date)}` : "—"}</dd></div>
          </dl>
        </details>
      </li>`).join("")}
    </ol>`;
  }

  function renderRankings(route) {
    setTitle("Rankings");
    content.innerHTML = `
      <div class="page">
        <header class="page-heading"><div><p class="eyebrow">Current international teams</p><h1>Rankings</h1></div><p class="lede">The rating combines estimated playing strength with an allowance for uncertainty. Teams with results against a broad range of opponents can therefore be assessed more confidently. <a href="#/history">Choose a historical date →</a></p></header>
        <div class="toolbar">
          <div class="field field-grow"><label for="ranking-search">Find a team</label><input id="ranking-search" type="search" placeholder="Search current teams…" value="${escapeHTML(route.query.get("q") || "")}"></div>
          <div class="field"><label for="ranking-sort">Sort</label><select id="ranking-sort"><option value="rating">Rating</option><option value="rating_change_12m">12-month rating change</option><option value="rank_change_12m">12-month rank change</option><option value="matches">Matches played</option><option value="name">Name</option></select></div>
          <div class="toggle-group" role="group" aria-label="Ranking pool"><button class="button" data-pool="current" aria-pressed="false">Current teams</button><button class="button" data-pool="all" aria-pressed="false">All teams, including historical</button></div>
        </div>
        <div class="record-note"><strong>Rating</strong><div><b>One cautious rating is used throughout the site.</b> Current teams need at least 30 matches and an appearance in the current calendar year or one of the preceding four calendar years. The 12-month column compares the latest eligible matchday with the equivalent point one year earlier.</div></div>
        <div id="rankings-table"></div>
      </div>`;
    const target = document.getElementById("rankings-table");
    document.getElementById("ranking-search").placeholder = (
      shuffledExamples(
        summary.current.map((team) => team.nation),
      )
      || "Search current teams…"
    );
    let pool = route.query.get("pool") === "all" ? "all" : "current";
    const requestedSort = ["rating", "rating_change_12m", "rank_change_12m", "matches", "name"].includes(route.query.get("sort")) ? route.query.get("sort") : "rating";
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
      const query = foldSearch(document.getElementById("ranking-search").value);
      const sort = document.getElementById("ranking-sort").value;
      const source = pool === "current" ? summary.current : summary.teams;
      const ratingRanks = new Map([...source].sort((a, b) => b.rating - a.rating || a.nation.localeCompare(b.nation)).map((team, index) => [team.code, index + 1]));
      const filtered = source.filter((team) => teamSearchText(team.code, team.nation).includes(query));
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

  function historicalRankingFromPayload(
    index,
    payload,
    chosen,
    beforeDate = false,
  ) {
    const includesDate = (value) => (
      beforeDate ? value < chosen : value <= chosen
    );
    const state = new Map(
      payload.opening.map((team) => [team.code, { ...team }]),
    );
    payload.events.forEach((event) => {
      if (includesDate(event.date)) {
        state.set(event.code, { ...event });
      }
    });

    let snapshot = payload.global_opening || null;
    (payload.global_snapshots || []).forEach((candidate) => {
      if (includesDate(candidate[0])) snapshot = candidate;
    });
    if (!snapshot || !Array.isArray(index.codes)) {
      const legacy = [...state.values()]
        .filter((team) => (
          Number(chosen.slice(0, 4))
          - Number(team.date.slice(0, 4))
          <= 4
        ))
        .map((team) => projectTeamRating(team, chosen))
        .sort((a, b) => (
          b.rating - a.rating
          || a.nation.localeCompare(b.nation)
        ));
      legacy.forEach((team, position) => {
        team.rank = position + 1;
      });
      return legacy;
    }

    const baseline = Number(snapshot[1]);
    const targetDay = modelDayNumber(chosen);
    const drift = Number(summary.parameters.network.drift_sd);
    const selectedYear = Number(chosen.slice(0, 4));
    const ranked = snapshot[2].flatMap((row) => {
      const code = index.codes[Number(row[0])];
      const event = state.get(code);
      if (
        !event
        || selectedYear - Number(event.date.slice(0, 4)) > 4
      ) {
        return [];
      }
      const sourceDay = modelDayNumber(event.date);
      const elapsed = (
        sourceDay == null || targetDay == null
          ? 0
          : Math.max(0, (targetDay - sourceDay) / 400)
      );
      const variance = Math.max(
        0,
        Number(row[2]) + drift * drift * elapsed,
      );
      const se = Math.sqrt(variance);
      const mean = (
        2000
        + Number(event.reliability)
        * (Number(row[1]) - baseline)
      );
      return [{
        ...event,
        code,
        rating: mean - confidenceZ * se,
        mean,
        se,
        latent: 1500 + Number(row[1]),
        rating_date: chosen,
        snapshot_date: snapshot[0],
      }];
    }).sort((a, b) => (
      b.rating - a.rating
      || a.nation.localeCompare(b.nation)
    ));
    ranked.forEach((team, position) => {
      team.rank = position + 1;
    });
    return ranked;
  }

  async function loadHistoricalSnapshot(index, value) {
    const chosen = value < index.first ? index.first : value;
    const dataDate = chosen > index.last ? index.last : chosen;
    const dataYear = Math.min(
      Number(dataDate.slice(0, 4)),
      Number(index.last.slice(0, 4)),
    );
    const payload = await getJSON(`data/rankings-history/${dataYear}.json`);
    return historicalRankingFromPayload(
      index,
      payload,
      dataDate,
    );
  }

  function historicalRankingsTable(items, selectedDate) {
    if (!items.length) return `<div class="empty"><h2>No eligible rankings yet</h2><p>Teams enter the table after their 30th recorded match.</p></div>`;
    return `<div class="ranking-desktop"><div class="table-shell"><table class="ranking-table">
      <thead><tr><th class="numeric">Rank</th><th>Team</th><th class="numeric">Rating</th><th class="numeric hide-mobile">Underlying strength estimate</th><th class="numeric hide-mobile">Matches</th><th>Recent form</th><th class="hide-mobile">Last match</th></tr></thead>
      <tbody>${items.map((team, index) => `<tr><td class="rank-cell numeric">${team.rank ?? index + 1}</td><td>${teamLink(team.code, team.nation, selectedDate)}</td>
        <td class="numeric"><span class="rating-main">${rating(team.rating)}</span><span class="rating-sub">uncertainty ${rating(team.se)}</span></td>
        <td class="numeric hide-mobile">${rating(team.mean)}</td><td class="numeric hide-mobile">${number(team.matches)}</td>
        <td>${formHTML(team.form || [])}</td><td class="hide-mobile">${validDate(team.date)}</td></tr>`).join("")}</tbody></table></div></div>
      <ol class="ranking-cards" aria-label="Historical rankings">
        ${items.map((team, index) => `<li class="ranking-card">
          <div class="ranking-card-heading">
            <span class="ranking-card-rank">No. ${team.rank ?? index + 1}</span>
            <div class="ranking-card-rating"><strong>${rating(team.rating)}</strong><small>uncertainty ${rating(team.se)}</small></div>
          </div>
          <div class="ranking-card-team">${teamLink(team.code, team.nation, selectedDate)}</div>
          <div class="ranking-card-snapshot ranking-card-snapshot-single">
            <div><span>Recent form</span>${formHTML(team.form || [])}</div>
          </div>
          <details class="ranking-card-details">
            <summary>More ranking details</summary>
            <dl>
              <div><dt>Underlying strength estimate</dt><dd>${rating(team.mean)}</dd></div>
              <div><dt>Matches</dt><dd>${number(team.matches)}</dd></div>
              <div><dt>Last match</dt><dd>${validDate(team.date)}</dd></div>
            </dl>
          </details>
        </li>`).join("")}
      </ol>`;
  }

  async function renderHistory(route) {
    setTitle("Historical rankings");
    loading("Loading historical rankings…");
    const index = await getJSON("data/rankings-history/index.json");
    const today = todayISO();
    const requested = isoDate(route.query.get("date")) || today;
    const selected = requested < index.first ? index.first : requested > today ? today : requested;
    content.innerHTML = `<div class="page">
      <header class="page-heading"><div><p class="eyebrow">Rankings on any date</p><h1>Historical rankings</h1></div><p class="lede">Reconstructed with the current model after every match played on or before the selected date. These are present-day estimates of the past, not tables published at the time. <a href="#/tournaments">Compare tournament snapshots →</a></p></header>
      <div class="toolbar history-toolbar">
        <div class="history-date-actions"><div class="field history-date-field"><label for="history-date">Ranking date</label><div class="date-combo"><input id="history-date" type="text" inputmode="numeric" autocomplete="off" maxlength="10" placeholder="DD/MM/YYYY" value="${validDate(selected)}" aria-describedby="history-date-error"><button class="button" type="button" id="history-calendar-button" aria-label="Open calendar">Calendar</button><input id="history-calendar" class="native-date-proxy" type="date" min="${index.first}" max="${today}" value="${selected}" tabindex="-1" aria-hidden="true" aria-label="Ranking date calendar"></div><span id="history-date-error" class="field-error" role="alert"></span></div><button class="button button-dark" type="button" id="history-apply">Apply date</button></div>
        <div class="history-nav-actions"><button class="button" type="button" id="history-prev">← Previous matchday</button><button class="button" type="button" id="history-next">Next matchday →</button><button class="button button-quiet" type="button" id="history-year-start">Start of selected year</button></div>
      </div>
      <div class="record-note"><strong id="history-count">—</strong><div><b id="history-label">Eligible teams</b><br>At least 30 matches and an appearance in the selected year or preceding four calendar years.</div></div>
      <div class="toolbar compact-toolbar"><div class="field field-grow"><label for="history-search">Find a team</label><input id="history-search" type="search" placeholder="Search teams on this date…" value="${escapeHTML(route.query.get("q") || "")}"></div><div class="field"><label for="history-sort">Sort</label><select id="history-sort"><option value="rating">Rating</option><option value="matches">Matches played</option><option value="name">Name</option></select></div></div>
      <div id="history-table"></div></div>`;

    let teams = [];
    let currentDate = selected;
    const dateInput = document.getElementById("history-date");
    const calendarInput = document.getElementById("history-calendar");
    const table = document.getElementById("history-table");
    const requestedSort = ["rating", "matches", "name"].includes(route.query.get("sort")) ? route.query.get("sort") : "rating";
    document.getElementById("history-sort").value = requestedSort;

    const saveHistoryRoute = () => replaceRouteQuery("history", {
      date: currentDate,
      q: document.getElementById("history-search").value.trim(),
      sort: document.getElementById("history-sort").value === "rating" ? "" : document.getElementById("history-sort").value,
    });

    const updateTable = () => {
      const query = foldSearch(document.getElementById("history-search").value);
      const sort = document.getElementById("history-sort").value;
      const visible = teams.filter((team) => teamSearchText(team.code, team.nation).includes(query));
      visible.sort((a, b) => sort === "name"
        ? a.nation.localeCompare(b.nation)
        : (b[sort] ?? -Infinity) - (a[sort] ?? -Infinity) || a.nation.localeCompare(b.nation));

table.innerHTML = (!visible.length && query)
  ? filteredEmptyState("teams")
  : historicalRankingsTable(visible, currentDate);
    };

    const loadDate = async (value) => {
      const chosen = value < index.first ? index.first : value > today ? today : value;
      currentDate = chosen;
      dateInput.value = validDate(chosen);
      calendarInput.value = chosen;
      document.getElementById("history-date-error").textContent = "";
      dateInput.removeAttribute("aria-invalid");
      document.getElementById("history-prev").disabled = chosen <= index.first;
      document.getElementById("history-next").disabled = (
        chosen >= (index.last_matchday || index.last)
      );
      saveHistoryRoute();
      table.innerHTML = `<div class="loading-shell" role="status"><span class="spinner" aria-hidden="true"></span><p>Loading ${escapeHTML(validDate(chosen))}…</p></div>`;
      teams = await loadHistoricalSnapshot(index, chosen);
      document.getElementById("history-search").placeholder = (
        shuffledExamples(
          teams.map((team) => team.nation),
        )
        || "Search teams on this date…"
      );
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
      const error = historyDateInputError(dateInput.value, index.first, today);
      if (!chosen || error) {
        document.getElementById("history-date-error").textContent = error || "Enter a complete date as DD/MM/YYYY.";
        dateInput.setAttribute("aria-invalid", "true");
        return;
      }
      loadDate(chosen);
    };

    const syncTypedDate = () => {
      dateInput.value = formatHistoryDateInput(dateInput.value);
      const error = historyDateInputError(dateInput.value, index.first, today);
      document.getElementById("history-date-error").textContent = error;
      if (error) dateInput.setAttribute("aria-invalid", "true");
      else dateInput.removeAttribute("aria-invalid");
    };

    document.getElementById("history-apply").addEventListener("click", applyTypedDate);
    dateInput.addEventListener("input", syncTypedDate);
    dateInput.addEventListener("keydown", (event) => {
      if (event.key === "Enter") applyTypedDate();
      if (event.key === "Backspace" && dateInput.selectionStart === dateInput.selectionEnd && [3, 6].includes(dateInput.selectionStart)) {
        event.preventDefault();
        const position = dateInput.selectionStart;
        dateInput.value = `${dateInput.value.slice(0, position - 2)}${dateInput.value.slice(position)}`;
        syncTypedDate();
        dateInput.setSelectionRange(position - 2, position - 2);
      }
    });
    document.getElementById("history-calendar-button").addEventListener("click", () => {
      if (typeof calendarInput.showPicker === "function") calendarInput.showPicker();
      else calendarInput.click();
    });
    calendarInput.addEventListener("change", () => { if (calendarInput.value) loadDate(calendarInput.value); });
    document.getElementById("history-year-start").addEventListener("click", () => loadDate(`${currentDate.slice(0, 4)}-01-01`));
    document.getElementById("history-prev").addEventListener("click", () => adjacentMatchday(-1));
    document.getElementById("history-next").addEventListener("click", () => adjacentMatchday(1));
    document.getElementById("history-search").addEventListener("input", () => { saveHistoryRoute(); updateTable(); });
    document.getElementById("history-sort").addEventListener("change", () => { saveHistoryRoute(); updateTable(); });
    await loadDate(selected);
  }


  function tournamentChangeHTML(value, kind) {
    if (value == null || !Number.isFinite(Number(value))) {
      return `<span class="tournament-change movement-flat" title="No comparable published ${kind}">—</span>`;
    }
    const change = Number(value);
    const direction = change > 0
      ? "movement-up"
      : change < 0
        ? "movement-down"
        : "movement-flat";
    const arrow = change > 0 ? "▲" : change < 0 ? "▼" : "•";
    if (kind === "rank") {
      const places = Math.abs(change);
      const label = change === 0
        ? "No rank movement"
        : `${places} place${places === 1 ? "" : "s"} ${change > 0 ? "up" : "down"}`;
      return `<span class="tournament-change ${direction}" title="${label} during this tournament">${arrow} ${places}</span>`;
    }
    const signed = `${change >= 0 ? "+" : ""}${rating(change)}`;
    return `<span class="tournament-change ${direction}" title="Rating change attributed to this tournament\'s matches: ${signed} points">${arrow} ${signed}</span>`;
  }

  function tournamentRankingsTable(items, selectedDate, showMovement) {
    if (!items.length) {
      return `<div class="empty"><h2>No participants</h2><p>No participating teams were recorded for this edition.</p></div>`;
    }
    return `<div class="ranking-desktop"><div class="table-shell tournament-table"><table class="ranking-table">
      <thead><tr><th class="numeric">Rank</th><th>Team</th><th class="numeric">Rating</th><th class="numeric hide-mobile">Underlying strength estimate</th><th class="numeric hide-mobile">Matches</th><th>Recent form</th><th class="hide-mobile">Last match</th></tr></thead>
      <tbody>${items.map((team) => {
        const rankValue = team.rank == null ? "—" : team.rank;
        const ratingNote = team.rating == null
          ? "Not rated"
          : `uncertainty ${rating(team.se)}`;
        return `<tr>
          <td class="rank-cell numeric"><span class="tournament-cell-main">${rankValue}</span>${showMovement ? tournamentChangeHTML(team.tournament_rank_change, "rank") : ""}</td>
          <td>${teamLink(team.code, team.nation, selectedDate)}</td>
          <td class="numeric"><span class="rating-main">${rating(team.rating)}</span>${showMovement ? tournamentChangeHTML(team.tournament_rating_change, "rating") : ""}<span class="rating-sub">${ratingNote}</span></td>
          <td class="numeric hide-mobile">${rating(team.mean)}</td>
          <td class="numeric hide-mobile">${team.matches == null ? "—" : number(team.matches)}</td>
          <td>${team.form?.length ? formHTML(team.form) : `<span class="muted">—</span>`}</td>
          <td class="hide-mobile">${team.date ? validDate(team.date) : "—"}</td>
        </tr>`;
      }).join("")}</tbody></table></div></div>
      <ol class="ranking-cards" aria-label="Tournament rankings">
        ${items.map((team) => {
          const rankValue = team.rank == null ? "—" : team.rank;
          const ratingNote = team.rating == null
            ? "Not rated"
            : `uncertainty ${rating(team.se)}`;
          return `<li class="ranking-card">
            <div class="ranking-card-heading">
              <div class="ranking-card-rank">No. ${rankValue}${showMovement ? tournamentChangeHTML(team.tournament_rank_change, "rank") : ""}</div>
              <div class="ranking-card-rating"><strong>${rating(team.rating)}</strong>${showMovement ? tournamentChangeHTML(team.tournament_rating_change, "rating") : ""}<small>${ratingNote}</small></div>
            </div>
            <div class="ranking-card-team">${teamLink(team.code, team.nation, selectedDate)}</div>
            <div class="ranking-card-snapshot ranking-card-snapshot-single">
              <div><span>Recent form</span>${team.form?.length ? formHTML(team.form) : `<span class="muted">—</span>`}</div>
            </div>
            <details class="ranking-card-details">
              <summary>More ranking details</summary>
              <dl>
                <div><dt>Underlying strength estimate</dt><dd>${rating(team.mean)}</dd></div>
                <div><dt>Matches</dt><dd>${team.matches == null ? "—" : number(team.matches)}</dd></div>
                <div><dt>Last match</dt><dd>${team.date ? validDate(team.date) : "—"}</dd></div>
              </dl>
            </details>
          </li>`;
        }).join("")}
      </ol>`;
  }


const MAJOR_TOURNAMENT_PRECEDENCE = [
  "FIFA World Cup",
  "UEFA European Championship",
  "Copa América",
  "Africa Cup of Nations",
  "AFC Asian Cup",
  "CONCACAF Gold Cup",
  "OFC Nations Cup",
];


function defaultMajorTournamentFamily(families) {
  const major = families
    .filter(
      (family) => (
        MAJOR_TOURNAMENT_PRECEDENCE.includes(
          family.name,
        )
        && family.editions?.length
      ),
    )
    .map((family) => {
      const edition = [...family.editions].sort(
        (first, second) => (
          String(second.after).localeCompare(
            String(first.after),
          )
        ),
      )[0];
      return {
        family,
        edition,
        ongoing: Boolean(edition.ongoing),
        time: new Date(
          `${edition.after}T00:00:00Z`,
        ).valueOf(),
      };
    })
    .filter((candidate) => Number.isFinite(candidate.time));

  if (!major.length) return null;

  const byPrecedence = (candidates) => [...candidates].sort(
    (first, second) => (
      MAJOR_TOURNAMENT_PRECEDENCE.indexOf(
        first.family.name,
      )
      - MAJOR_TOURNAMENT_PRECEDENCE.indexOf(
        second.family.name,
      )
      || second.time - first.time
    ),
  );

  const ongoing = major.filter(
    (candidate) => candidate.ongoing,
  );
  if (ongoing.length) {
    return byPrecedence(ongoing)[0]?.family || null;
  }

  const newestTime = Math.max(
    ...major.map((candidate) => candidate.time),
  );
  const thirtyDays = 30 * 24 * 60 * 60 * 1000;
  const closeTogether = major.filter(
    (candidate) => (
      newestTime - candidate.time <= thirtyDays
    ),
  );
  return byPrecedence(closeTogether)[0]?.family || null;
}

  async function renderTournaments(route) {
    setTitle("Tournament rankings");
    loading("Loading tournament rankings…");
    const [historyIndex, tournamentIndex] = await Promise.all([
      getJSON("data/rankings-history/index.json"),
      getJSON("data/tournaments/index.json"),
    ]);
    const families = tournamentIndex.families || [];
    if (!families.length) {
      content.innerHTML = `<div class="error-panel"><p class="eyebrow">Tournament archive</p><h2>No tournament editions are available.</h2><p>The build did not identify any completed competitive tournament editions.</p></div>`;
      return;
    }

    const requestedFamily = families.find(
      (family) => family.id === route.query.get("tournament"),
    );
    const defaultFamily = (
      defaultMajorTournamentFamily(families)
      || families[0]
    );
    let selectedFamily = requestedFamily || defaultFamily;
    let selectedEdition = selectedFamily.editions.find(
      (edition) => edition.id === route.query.get("edition"),
    ) || selectedFamily.editions[0];
    let selectedView = route.query.get("view") === "before"
      ? "before"
      : "after";

    const familyOptions = (tournamentIndex.categories || []).map(
      (category) => {
        const options = families
          .filter((family) => family.category === category)
          .map((family) => `<option value="${escapeHTML(family.id)}">${escapeHTML(family.name)}</option>`)
          .join("");
        return options
          ? `<optgroup label="${escapeHTML(category)}">${options}</optgroup>`
          : "";
      },
    ).join("");

    content.innerHTML = `<div class="page tournament-page">
      <header class="page-heading"><div><p class="eyebrow">Tournament snapshots</p><h1>Tournaments</h1></div><p class="lede">Choose a tournament and edition to compare every participant immediately before or after the event. Ranks always refer to the full world ranking, not just the teams in that tournament.</p></header>
      <div class="toolbar tournament-toolbar">
        <div class="field field-grow"><label for="tournament-family">Tournament</label><select id="tournament-family">${familyOptions}</select></div>
        <div class="field"><label for="tournament-edition">Edition</label><select id="tournament-edition"></select></div>
        <div class="field"><label for="tournament-view">Snapshot</label><select id="tournament-view"><option value="before">Before tournament</option><option value="after">After tournament</option></select></div>
      </div>
      <div class="record-note"><strong id="tournament-count">—</strong><div><b id="tournament-label">Participants</b><br><span id="tournament-description">Choose a tournament edition.</span></div></div>
      <div class="toolbar compact-toolbar">
        <div class="field field-grow"><label for="tournament-search">Find a team</label><input id="tournament-search" type="search" list="tournament-team-suggestions" placeholder="Search tournament teams…" value="${escapeHTML(route.query.get("q") || "")}"><datalist id="tournament-team-suggestions"></datalist></div>
        <div class="field"><label for="tournament-sort">Sort</label><select id="tournament-sort"></select></div>
      </div>
      <div id="tournament-table"></div>
    </div>`;

    const familySelect = document.getElementById("tournament-family");
    const editionSelect = document.getElementById("tournament-edition");
    const viewSelect = document.getElementById("tournament-view");
    const sortSelect = document.getElementById("tournament-sort");
    const table = document.getElementById("tournament-table");
    const summaryNames = new Map(
      summary.teams.map((team) => [team.code, team.nation]),
    );
    const requestedSortValue = route.query.get("sort");
        const requestedSort = requestedSortValue === "rating_gain"
          ? "rating_change"
          : requestedSortValue || "rating";
    familySelect.value = selectedFamily.id;
    viewSelect.value = selectedView;
    let teams = [];

    const populateEditions = (preferredId = "") => {
      editionSelect.innerHTML = selectedFamily.editions
        .map((edition) => `<option value="${escapeHTML(edition.id)}">${escapeHTML(edition.label)}</option>`)
        .join("");
      selectedEdition = selectedFamily.editions.find(
        (edition) => edition.id === preferredId,
      ) || selectedFamily.editions[0];
      editionSelect.value = selectedEdition.id;
    };

    const syncSortOptions = (preferred = sortSelect.value || requestedSort) => {
      sortSelect.innerHTML = selectedView === "after"
        ? `<option value="rating">Rating</option><option value="rating_change">Rating change</option><option value="rank_change">Rank change</option><option value="name">Name</option>`
        : `<option value="rating">Rating</option><option value="name">Name</option>`;
      const allowed = selectedView === "after"
        ? new Set(["rating", "rating_change", "rank_change", "name"])
        : new Set(["rating", "name"]);
      sortSelect.value = allowed.has(preferred)
        ? preferred
        : "rating";
    };

    populateEditions(selectedEdition.id);
    syncSortOptions();

    const saveTournamentRoute = () => replaceRouteQuery(
      "tournaments",
      {
        tournament: selectedFamily.id,
        edition: selectedEdition.id,
        view: selectedView,
        q: document.getElementById("tournament-search").value.trim(),
        sort: sortSelect.value === "rating"
          ? ""
          : sortSelect.value,
      },
    );

    const descendingValue = (team, key) => {
      if (team[key] == null || team[key] === "") return -Infinity;
      const value = Number(team[key]);
      return Number.isFinite(value) ? value : -Infinity;
    };

    const updateTable = () => {
      const query = document
        .getElementById("tournament-search")
        .value.trim()
        .toLocaleLowerCase();
      const sort = sortSelect.value;
      const visible = teams.filter(
        (team) => team.search_names.includes(query),
      );
      visible.sort((a, b) => {
        if (sort === "name") {
          return a.nation.localeCompare(b.nation);
        }
        if (sort === "rating_change") {
          return (
            descendingValue(b, "tournament_rating_change")
            - descendingValue(a, "tournament_rating_change")
            || a.nation.localeCompare(b.nation)
          );
        }
        if (sort === "rank_change") {
          return (
            descendingValue(b, "tournament_rank_change")
            - descendingValue(a, "tournament_rank_change")
            || a.nation.localeCompare(b.nation)
          );
        }
        return (
          descendingValue(b, "rating")
          - descendingValue(a, "rating")
          || a.nation.localeCompare(b.nation)
        );
      });
      table.innerHTML = tournamentRankingsTable(
        visible,
        selectedEdition[selectedView],
        selectedView === "after",
      );
    };

    const editionParticipants = () => {
      if (Array.isArray(selectedEdition.participants)) {
        return selectedEdition.participants;
      }
      return (selectedEdition.teams || []).map((code) => ({
        code,
        nation: summaryNames.get(code) || code,
      }));
    };

    const updateTournamentSearchPlaceholder = (participants) => {
          const names = [
            ...new Set(
              participants
                .map(
                  (participant) => (
                    publicTeamName(participant.nation)
                    || publicTeamName(summaryNames.get(participant.code))
                    || participant.code
                  ),
                )
                .filter(Boolean),
            ),
          ];

          for (
            let index = names.length - 1;
            index > 0;
            index -= 1
          ) {
            const swapIndex = Math.floor(
              Math.random() * (index + 1),
            );
            [names[index], names[swapIndex]] = [
              names[swapIndex],
              names[index],
            ];
          }

          const examples = names.slice(
            0,
            Math.min(3, names.length),
          );
          const suffix = examples.length < names.length
            ? "…"
            : "";

          document.getElementById(
            "tournament-team-suggestions",
          ).innerHTML = names
            .map(
              (name) => (
                `<option value="${escapeHTML(name)}"></option>`
              ),
            )
            .join("");

          document.getElementById(
            "tournament-search",
          ).placeholder = examples.length
            ? `${examples.join(", ")}${suffix}`
            : "Search tournament teams…";
        };

    const loadSelection = async () => {
      syncSortOptions();
      saveTournamentRoute();
      const snapshotDate = selectedEdition[selectedView];
      table.innerHTML = `<div class="loading-shell" role="status"><span class="spinner" aria-hidden="true"></span><p>Loading ${escapeHTML(selectedFamily.name)} ${escapeHTML(selectedEdition.label)}…</p></div>`;

      const ranked = await loadHistoricalSnapshot(
        historyIndex,
        snapshotDate,
      );
      const rankedByCode = new Map(
        ranked.map((team) => [team.code, team]),
      );
      const participants = editionParticipants();
      updateTournamentSearchPlaceholder(participants);
      teams = participants.map((participant) => {
        const rankedTeam = rankedByCode.get(participant.code);
        if (rankedTeam) {
          return {
            ...rankedTeam,
            nation: rankedTeam.nation
              || participant.nation
              || summaryNames.get(participant.code)
              || participant.code,
          };
        }
        return {
          code: participant.code,
          nation: participant.nation
            || summaryNames.get(participant.code)
            || participant.code,
          rank: null,
          rating: null,
          mean: null,
          se: null,
          matches: null,
          form: [],
          date: null,
        };
      });

      const historicalParticipantNames = new Map(
            participants.map(
              (participant) => [
                participant.code,
                participant.nation || "",
              ],
            ),
          );
          teams = teams.map((team) => ({
            ...team,
            search_names: teamSearchText(
              team.code,
              team.nation,
              historicalParticipantNames.get(team.code),
              summaryNames.get(team.code),
            ),
          }));

                if (selectedView === "after") {
        const beforeRanked = await loadHistoricalSnapshot(
          historyIndex,
          selectedEdition.before,
        );
        const beforeByCode = new Map(
          beforeRanked.map((team) => [team.code, team]),
        );

                const attributedChanges = new Map(
                  (selectedEdition.rating_changes || [])
                    .filter(
                      (item) => (
                        item.change != null
                        && Number.isFinite(Number(item.change))
                      ),
                    )
                    .map(
                      (item) => [
                        item.code,
                        Number(item.change),
                      ],
                    ),
                );

        teams = teams.map((team) => {
          const before = beforeByCode.get(team.code);
          const comparable = before && team.rating != null;
          return {
            ...team,
            tournament_rank_change: (
              comparable && team.rank != null
                ? before.rank - team.rank
                : null
            ),
            tournament_rating_change: (
              comparable && attributedChanges.has(team.code)
                ? attributedChanges.get(team.code)
                : null
            ),
          };
        });
      }

      // Tournament edition summary
          const rankedCount = teams.filter(
            (team) => team.rating != null,
          ).length;
          const unratedCount = teams.length - rankedCount;
          const coverageNote = unratedCount > 0
            ? ` All participants are shown, including teams without a published rating; ${number(unratedCount)} ${unratedCount === 1 ? "team was" : "teams were"} unrated ${selectedView === "after" ? "after" : "before"} the tournament.`
            : "";

          document.getElementById("tournament-count").textContent =
            number(teams.length);
          document.getElementById("tournament-label").textContent =
            `${selectedFamily.name} · ${selectedEdition.label}`;
          document.getElementById("tournament-description").textContent =
            selectedView === "after"
              ? `Final snapshot: ${validDate(selectedEdition.after)}. Rank change compares each team's place in the full world ranking. Rating change includes only matches from this edition, excluding recalibration and unrelated results.${coverageNote}`
              : `Pre-tournament snapshot: ${validDate(selectedEdition.before)}. The tournament ended on ${validDate(selectedEdition.end)}.${coverageNote}`;
      setTitle(
        `${selectedFamily.name} ${selectedEdition.label}`,
      );
      updateTable();
    };

    familySelect.addEventListener("change", () => {
      selectedFamily = families.find(
        (family) => family.id === familySelect.value,
      ) || families[0];
      populateEditions();
      loadSelection();
    });
    editionSelect.addEventListener("change", () => {
      selectedEdition = selectedFamily.editions.find(
        (edition) => edition.id === editionSelect.value,
      ) || selectedFamily.editions[0];
      loadSelection();
    });
    viewSelect.addEventListener("change", () => {
      selectedView = viewSelect.value === "before"
        ? "before"
        : "after";
      syncSortOptions();
      loadSelection();
    });
    document
      .getElementById("tournament-search")
      .addEventListener("input", () => {
        saveTournamentRoute();
        updateTable();
      });
    sortSelect.addEventListener("change", () => {
      saveTournamentRoute();
      updateTable();
    });
    await loadSelection();
  }

  async function renderMatches(route) {
    setTitle("Matches");
    loading("Loading the historical match explorer…");
    const index = await getJSON("data/matches/index.json");
    const requestedTeam = route.query.get("team") || "";
    const latest = index.decades[index.decades.length - 1].decade;
    content.innerHTML = `
      <div class="page">
        <header class="page-heading"><div><p class="eyebrow">International results since 1872</p><h1>Matches</h1></div><p class="lede">Browse the complete match history. Probabilities and ratings are calculated using only information available before each match. A home forecast combines the era-wide baseline with both countries’ venue profiles; neutral matches receive neither adjustment.<span class="page-action-hint">Tap or click a probability bar for the full prediction and venue breakdown.</span></p></header>
        ${ratingForecastExplanation()}
        <div class="toolbar">
          <div class="field"><label for="match-decade">Era</label><select id="match-decade"><option value="all">All ${number(summary.meta.matches)} matches</option>${index.decades.slice().reverse().map((item) => `<option value="${item.decade}">${item.decade}s · ${number(item.count)}</option>`).join("")}</select></div>
          <div class="field"><label for="match-team">Team</label><select id="match-team"><option value="">Any team</option></select></div>
          <div class="field"><label for="match-class">Class</label><select id="match-class"><option value="">All classes</option><option value="friendly">Friendly</option><option value="competitive">Competitive</option></select></div>
          <div class="field field-grow"><label for="match-search">Competition or opponent</label><input id="match-search" type="search" placeholder="Competition, team or match class…" value="${escapeHTML(route.query.get("q") || "")}"></div>
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
    const currentNames = new Map(
      summary.teams.map(
        (team) => [team.code, publicTeamName(team.nation)],
      ),
    );
    const lineageNamesByCode = new Map(
      summary.teams.map((team) => [
        team.code,
        completePublicLineageNames([
          team.nation,
          ...(team.lineage_names || []),
        ]),
      ]),
    );
    const majorTeamCodes = new Set([
      "AR", "BE", "BR", "DE", "EN", "ES", "FR",
      "HR", "IT", "MX", "NL", "PT", "RU", "UY",
    ]);
    const majorCompetitionTokens = [
      "world cup",
      "european championship",
      "euro ",
      "copa america",
      "copa américa",
      "africa cup",
      "asian cup",
      "gold cup",
      "nations cup",
      "confederations cup",
      "olympic",
    ];

    const populateMatchTeamOptions = (
      matches,
      preferredCode,
      selectedEra,
    ) => {
      const namesByCode = new Map();
      const addName = (code, name, matchDate) => {
        const displayName = publicTeamName(name).trim();
        if (!code || !displayName) return;
        if (!namesByCode.has(code)) {
          namesByCode.set(code, []);
        }
        namesByCode.get(code).push({
          name: displayName,
          date: matchDate,
        });
      };
      matches.forEach((match) => {
        addName(match.a, match.an, match.date);
        addName(match.b, match.bn, match.date);
      });

      const options = [...namesByCode.entries()]
        .map(([code, occurrences]) => {
          const latestByName = new Map();
          occurrences.forEach(({ name, date }) => {
            const previous = latestByName.get(name) || "";
            if (date > previous) {
              latestByName.set(name, date);
            }
          });
          const historicalNames = [
            ...latestByName.entries(),
          ]
            .sort(
              (first, second) => (
                second[1].localeCompare(first[1])
                || first[0].localeCompare(second[0])
              ),
            )
            .map(([name]) => name);
          const currentName = currentNames.get(code);
          const primary = selectedEra === "all"
            ? (
              currentName
              || historicalNames[0]
              || code
            )
            : (
              historicalNames[0]
              || currentName
              || code
            );
          const aliases = completePublicLineageNames([
            primary,
            ...historicalNames,
            ...(lineageNamesByCode.get(code) || []),
          ]).filter((name) => name !== primary);
          const label = aliases.length
            ? `${primary} (incl. ${aliases.join(", ")})`
            : primary;
          return { code, label };
        })
        .sort(
          (first, second) => (
            first.label.localeCompare(second.label)
            || first.code.localeCompare(second.code)
          ),
        );

      const select = document.getElementById("match-team");
      select.innerHTML = (
        '<option value="">Any team</option>'
        + options.map(
          (team) => (
            `<option value="${escapeHTML(team.code)}">`
            + `${escapeHTML(team.label)}</option>`
          ),
        ).join("")
      );
      select.value = options.some(
        (team) => team.code === preferredCode,
      )
        ? preferredCode
        : "";
    };

    const updateMatchSearchPlaceholder = (matches) => {
      const competitions = [
        ...new Set(
          matches
            .map((match) => match.t)
            .filter(Boolean),
        ),
      ];
      const majorCompetitions = competitions.filter(
        (competition) => {
          const folded = foldSearch(competition);
          return majorCompetitionTokens.some(
            (token) => folded.includes(token),
          );
        },
      );

      const teamCounts = new Map();
      const latestTeamNames = new Map();
      const rememberTeam = (
        code,
        name,
        matchDate,
      ) => {
        teamCounts.set(
          code,
          (teamCounts.get(code) || 0) + 1,
        );
        const previous = latestTeamNames.get(code);
        if (!previous || matchDate > previous.date) {
          latestTeamNames.set(code, {
            date: matchDate,
            name: publicTeamName(name),
          });
        }
      };
      matches.forEach((match) => {
        rememberTeam(
          match.a,
          match.an,
          match.date,
        );
        rememberTeam(
          match.b,
          match.bn,
          match.date,
        );
      });
      const presentMajorTeams = [
        ...teamCounts.keys(),
      ].filter((code) => majorTeamCodes.has(code));
      const fallbackTeam = [
        ...teamCounts.entries(),
      ].sort(
        (first, second) => (
          second[1] - first[1]
          || first[0].localeCompare(second[0])
        ),
      )[0]?.[0];
      const teamCode = presentMajorTeams.length
        ? presentMajorTeams[
          Math.floor(
            Math.random() * presentMajorTeams.length
          )
        ]
        : fallbackTeam;
      const teamName = teamCode
        ? (
          latestTeamNames.get(teamCode)?.name
          || currentNames.get(teamCode)
        )
        : "";
      const competition = majorCompetitions.length
        ? majorCompetitions[
          Math.floor(
            Math.random() * majorCompetitions.length
          )
        ]
        : "";
      const classExample = Math.random() < 0.5
        ? "qualifier"
        : "friendly";
      const examples = [
        competition,
        teamName,
        classExample,
      ].filter(Boolean);
      document.getElementById(
        "match-search",
      ).placeholder = examples.length
        ? `${examples.join(", ")}…`
        : "Competition, team or match class…";
    };

    const saveMatchesRoute = () => replaceRouteQuery("matches", {
      era: document.getElementById("match-decade").value === String(latest) ? "" : document.getElementById("match-decade").value,
      team: document.getElementById("match-team").value,
      class: document.getElementById("match-class").value,
      q: document.getElementById("match-search").value.trim(),
      page: page ? page + 1 : "",
    });
    const load = async () => {
      const decade = document.getElementById("match-decade").value;
      const preferredTeam = (
        document.getElementById("match-team").value
        || requestedTeam
      );
      loadingTable();
      if (decade === "all") {
        rows = (await getJSON("data/matches/search.json")).matches.slice().reverse();
      } else {
        rows = (await getJSON(`data/matches/${decade}.json`)).matches.slice().reverse();
      }
      populateMatchTeamOptions(
        rows,
        preferredTeam,
        decade,
      );
      updateMatchSearchPlaceholder(rows);
      await update();
    };
    const loadingTable = () => { document.getElementById("match-table").innerHTML = `<div class="loading-shell" role="status"><span class="spinner" aria-hidden="true"></span><p>Loading matches…</p></div>`; };
    const filtered = () => {
      const team = document.getElementById("match-team").value;
      const cls = document.getElementById("match-class").value;
      const query = foldSearch(document.getElementById("match-search").value);
      return rows.filter((match) => {
        if (team && match.a !== team && match.b !== team) return false;
        if (cls === "friendly" && !match.friendly) return false;
        if (cls === "competitive" && match.friendly) return false;
        const matchSearch = foldSearch(
        [
          teamSearchText(
            match.a,
            match.an,
            match.ac,
          ),
          teamSearchText(
            match.b,
            match.bn,
            match.bc,
          ),
          match.t,
          match.friendly
            ? "friendly"
            : "competitive",
        ].join(" "),
      );
      if (query && !matchSearch.includes(query)) {
        return false;
      }
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
    if (!matches.length) return filteredEmptyState("matches");
    return `<div class="table-shell match-history-table"><table><thead><tr><th>Date</th><th>Match</th><th>H/A/N</th><th class="numeric">Score</th><th class="hide-mobile">Competition</th><th>Pre-match W/D/L</th><th>Team ratings before → after</th><th class="numeric">Combined pre-match rating</th></tr></thead><tbody>${matches.map((match) => `<tr>
      <td class="mono" data-label="Date">${validDate(match.date)}</td>
      <td data-label="Match">${teamLink(match.a, match.an)} <span class="muted">v</span> ${teamLink(match.b, match.bn)}</td>
      <td data-label="Venue">${venueHTML(matchSite(match, perspective))}</td>
      <td class="numeric" data-label="Score"><span class="score">${match.sa}–${match.sb}</span></td>
          <td class="hide-mobile" data-label="Competition">${escapeHTML(match.t)}</td>
      <td data-label="Forecast">${probabilityHTML(match.p, {
      date: match.date,
      first: match.a,
      second: match.b,
      venue: Number(match.home) || 0,
      matchId: match.id,
      matchClass: (
        match.friendly
          ? "friendly"
          : "competitive"
      ),
      label: (
        `Open full prediction for ${match.an} `
        + `versus ${match.bn}`
      ),
    })}</td>
      <td data-label="Team ratings"><span class="rating-pair"><b>${escapeHTML(publicTeamName(match.an))}</b> ${rating(match.pre_a)} → ${rating(match.post_a)}</span><span class="rating-pair"><b>${escapeHTML(publicTeamName(match.bn))}</b> ${rating(match.pre_b)} → ${rating(match.post_b)}</span></td>
      <td class="numeric" data-label="Combined pre-match">${rating(match.combined)}</td>
    </tr>`).join("")}</tbody></table></div>`;
  }

  function peakTable(peaks) {
    return `<div class="table-hint" aria-hidden="true">Swipe horizontally to see all columns →</div><div class="table-shell"><table><thead><tr><th class="numeric">Rank</th><th>Team</th><th class="numeric">Peak rating</th><th>Date</th><th>Peak-making result</th><th class="hide-mobile">Competition</th></tr></thead><tbody>${peaks.map((peak, index) => `<tr>
      <td class="rank-cell numeric">${index + 1}</td><td>${teamLink(peak.code, peak.display_nation || peak.nation)}</td><td class="numeric"><span class="rating-main">${rating(peak.rating)}</span><span class="rating-sub">underlying strength ${rating(peak.mean)} · uncertainty ${rating(peak.se)}</span></td><td>${validDate(peak.date)}</td><td>${escapeHTML(peak.historical_name)} ${escapeHTML(peak.score)} ${escapeHTML(peak.opponent)}</td><td class="hide-mobile">${escapeHTML(peak.tournament)}</td>
    </tr>`).join("")}</tbody></table></div>`;
  }

  function numberOneMatch(spell) {
    const matches = spell.matches || (spell.match ? [spell.match] : []);
    if (!matches.length) {
      return `<span class="chronology-cause chronology-cause-${escapeHTML(spell.cause || "indirect")}">${escapeHTML(
        spell.reason
        || "No direct match: network effects, inactivity decay or eligibility changed the order.",
      )}</span>`;
    }
    return matches.map((match) => `<span class="trigger-result">${teamLink(match.team1_code, match.team1, spell.from)} <span class="score">${number(match.score1)}–${number(match.score2)}</span> ${teamLink(match.team2_code, match.team2, spell.from)}<span class="rating-sub">${escapeHTML(match.competition)}</span></span>`).join("");
  }

  function numberOneTable(spells) {
    return `<div class="table-hint" aria-hidden="true">Swipe horizontally to see all columns →</div><div class="table-shell"><table><thead><tr><th>Team</th><th>From</th><th>Until</th><th class="numeric">Days</th><th class="numeric">Entry rating</th><th>Entry result or explanation</th><th>Displaced</th></tr></thead><tbody>${spells.map((spell) => `<tr>
      <td>${teamLink(spell.code, spell.nation, spell.from)}</td><td>${validDate(spell.from)}</td><td>${spell.to ? validDate(spell.to) : "<b>Current</b>"}</td><td class="numeric">${number(spell.days)}</td><td class="numeric"><span class="rating-main">${rating(spell.rating)}</span></td><td>${numberOneMatch(spell)}</td><td>${spell.displaced ? teamLink(spell.displaced_code, spell.displaced, spell.from) : "—"}</td>
    </tr>`).join("")}</tbody></table></div>`;
  }

  function numberOneSummaryTable(rows) {
    return `<div class="table-hint" aria-hidden="true">Swipe horizontally to see all columns →</div><div class="table-shell"><table><thead><tr><th class="numeric">Rank</th><th>Team</th><th class="numeric">Total days</th><th class="numeric">Spells</th><th>First reached No. 1</th><th>Latest date at No. 1</th></tr></thead><tbody>${rows.map((row, index) => `<tr>
      <td class="rank-cell numeric">${index + 1}</td><td>${teamLink(row.code, row.display_nation || row.nation)}</td><td class="numeric"><span class="rating-main">${number(row.days)}</span></td><td class="numeric">${number(row.spells)}</td><td>${validDate(row.first)}</td><td>${row.current ? "<b>Current</b>" : validDate(row.latest)}</td>
    </tr>`).join("")}</tbody></table></div>`;
  }

  function matchRecordTable(matches) {
    return `<div class="table-hint" aria-hidden="true">Swipe horizontally to see all columns →</div><div class="table-shell"><table><thead><tr><th class="numeric">Rank</th><th>Date</th><th>Match</th><th class="numeric">Score</th><th class="numeric">Combined rating</th><th class="hide-mobile">Competition</th></tr></thead><tbody>${matches.map((match, index) => `<tr>
      <td class="rank-cell numeric">${index + 1}</td><td>${validDate(match.date)}</td><td>${teamLink(match.code1, match.team1)} <span class="muted">v</span> ${teamLink(match.code2, match.team2)}</td><td class="numeric"><span class="score">${escapeHTML(match.score).replace("-", "–")}</span></td><td class="numeric"><span class="rating-main">${rating(match.combined)}</span><span class="rating-sub">combined underlying strength ${rating(match.combined_mean)} · uncertainty ${rating(match.combined_se)}</span></td><td class="hide-mobile">${escapeHTML(match.tournament)}</td>
    </tr>`).join("")}</tbody></table></div>`;
  }

  function upsetTable(matches) {
    return `<div class="table-hint" aria-hidden="true">Swipe horizontally to see all columns →</div><div class="table-shell"><table><thead><tr><th class="numeric">Rank</th><th>Date</th><th>Match</th><th class="numeric">Score</th><th class="numeric">Upset points</th><th>Points won / lost</th><th class="hide-mobile">Competition</th></tr></thead><tbody>${matches.map((match, index) => `<tr>
      <td class="rank-cell numeric">${index + 1}</td><td>${validDate(match.date)}</td><td>${teamLink(match.code1, match.team1)} <span class="muted">v</span> ${teamLink(match.code2, match.team2)}</td><td class="numeric"><span class="score">${escapeHTML(match.score).replace("-", "–")}</span></td><td class="numeric"><span class="rating-main">${rating(match.points)}</span></td><td>${escapeHTML(match.winner)} <b>+${rating(match.winner_gain)}</b><span class="rating-sub">${escapeHTML(match.loser)} −${rating(match.loser_loss)}</span></td><td class="hide-mobile">${escapeHTML(match.tournament)}</td>
    </tr>`).join("")}</tbody></table></div>`;
  }


  function bestTournamentTable(rows) {
    if (!rows.length) {
      return `<div class="empty"><h2>No tournament records match those filters.</h2><p>Choose another team or competition.</p></div>`;
    }

    return `<div class="table-hint" aria-hidden="true">Swipe horizontally to see all columns →</div><div class="table-shell"><table>
      <thead><tr><th class="numeric">Rank</th><th>Team</th><th>Tournament</th><th class="hide-mobile">Edition</th><th class="numeric">Rating gain</th><th class="numeric">Tournament rating before → after</th><th class="hide-mobile">Tournament ended</th></tr></thead>
      <tbody>${rows.map((row, index) => {
        const tournamentURL = `#/tournaments?tournament=${encodeURIComponent(row.tournament_id)}&edition=${encodeURIComponent(row.edition_id)}&view=after`;
        return `<tr>
          <td class="rank-cell numeric">${index + 1}</td>
          <td>${teamLink(row.code, row.nation, row.after)}</td>
          <td><a class="team-link" href="${tournamentURL}">${escapeHTML(row.tournament)}</a></td>
          <td class="hide-mobile">${escapeHTML(row.edition)}</td>
          <td class="numeric"><span class="rating-main movement-up">+${rating(row.rating_gain)}</span></td>
          <td class="numeric"><span class="rating-pair">${rating(row.before_rating)} → ${rating(row.after_rating)}</span></td>
          <td class="hide-mobile">${validDate(row.after)}</td>
        </tr>`;
      }).join("")}</tbody>
    </table></div>`;
  }


function renderRecords(route) {
  setTitle("Records");
  const recordTeamByCode = new Map(
    summary.teams.map((team) => [team.code, team]),
  );
  const currentRecordName = (code) => publicTeamName(
    recordTeamByCode.get(code)?.nation || code,
  );
    const uniqueRecordNames = completePublicLineageNames;

  const currentFirstRecordLabel = (code, values) => {
    const team = recordTeamByCode.get(code);
    const current = currentRecordName(code);
    const names = uniqueRecordNames([
      current,
      ...(team?.lineage_names || []),
      ...values,
    ]);
    const first = current || names[0] || code;
    const included = names.filter((name) => name !== first);
    return included.length
      ? `${first} (incl. ${included.join(", ")})`
      : first;
  };

  const peakRecordLabel = (peak) => {
    const team = recordTeamByCode.get(peak.code);
    const current = currentRecordName(peak.code);
    const peakName = publicTeamName(
      peak.historical_name || peak.nation,
    );
    const lineage = uniqueRecordNames([
      peakName,
      current,
      ...(team?.lineage_names || []),
    ]);
    const first = peakName || current || peak.code;
    const included = lineage.filter((name) => name !== first);
    return included.length
      ? `${first} (incl. ${included.join(", ")})`
      : first;
  };

  const peakRows = (summary.peaks || [])
    .slice(0, 500)
    .map((row) => ({
      ...row,
      display_nation: peakRecordLabel(row),
    }));
  const numberOneRows = summary.number_ones || [];
  const numberOneSummaryRows = (
    summary.number_one_summary || []
  ).map((row) => ({
    ...row,
    display_nation: row.included_names?.length
      ? (
        `${publicTeamName(row.nation)} `
        + `(incl. ${row.included_names
          .map(publicTeamName)
          .join(", ")})`
      )
      : publicTeamName(row.nation),
  }));
  const highestMatchRows = (
    summary.top_matches || []
  ).slice(0, 500);
  const upsetRows = (summary.upsets || []).slice(0, 500);
  const bestTournamentRows = (
    summary.best_tournaments || []
  ).slice(0, 500);

  const pairSources = {
    matches: highestMatchRows,
    upsets: upsetRows,
    tournaments: bestTournamentRows,
  };
  const pairViews = new Set(Object.keys(pairSources));

  const recordTeamChoices = (rows, recordView) => {
    const namesByCode = new Map();
    const add = (code, name) => {
      if (!code) return;
      if (!namesByCode.has(code)) {
        namesByCode.set(code, []);
      }
      namesByCode.get(code).push(name);
    };
    rows.forEach((row) => {
      if (recordView === "tournaments") {
        add(row.code, row.nation);
      } else {
        add(row.code1, row.team1);
        add(row.code2, row.team2);
      }
    });
    return [...namesByCode.entries()]
      .map(([code, names]) => ({
        code,
        label: currentFirstRecordLabel(code, names),
      }))
      .sort(
        (first, second) => (
          first.label.localeCompare(second.label)
          || first.code.localeCompare(second.code)
        ),
      );
  };

  const recordCompetitions = (rows) => [
    ...new Set(
      rows
        .map((row) => row.tournament)
        .filter(Boolean),
    ),
  ].sort((first, second) => first.localeCompare(second));

  const peakPlaceholder = (
    shuffledExamples(
      peakRows.map((row) => row.display_nation),
    )
    || "Search peak teams…"
  );
  const numberOnePlaceholder = (
    shuffledExamples(
      numberOneRows.map((row) => row.nation),
    )
    || "Search former No. 1 teams…"
  );

  content.innerHTML = `
    <div class="page">
      <header class="page-heading"><div><p class="eyebrow">Historical rating records</p><h1>Records</h1></div><p class="lede">Explore team peaks, No. 1 chronology and totals, highest-rated matches, largest upsets and the biggest tournament rating gains.</p></header>
      <div class="record-tabs" role="tablist" aria-label="Record type"><button class="button button-dark" role="tab" aria-controls="record-table" data-record="peaks" aria-pressed="true" aria-selected="true" tabindex="0">Team peaks</button><button class="button" role="tab" aria-controls="record-table" data-record="numberones" aria-pressed="false" aria-selected="false" tabindex="-1">No. 1 chronology</button><button class="button" role="tab" aria-controls="record-table" data-record="numberonesummary" aria-pressed="false" aria-selected="false" tabindex="-1">No. 1 totals</button><button class="button" role="tab" aria-controls="record-table" data-record="matches" aria-pressed="false" aria-selected="false" tabindex="-1">Highest-rated matches</button><button class="button" role="tab" aria-controls="record-table" data-record="upsets" aria-pressed="false" aria-selected="false" tabindex="-1">Largest upsets</button><button class="button" role="tab" aria-controls="record-table" data-record="tournaments" aria-pressed="false" aria-selected="false" tabindex="-1">Tournament gains</button></div>

      <div id="peak-filters" class="toolbar record-filters" hidden>
        <div class="field field-grow"><label for="peak-team-search">Find a team</label><input id="peak-team-search" type="search" placeholder="${escapeHTML(peakPlaceholder)}" value="${escapeHTML(route.query.get("peak") || "")}"></div>
      </div>

      <div id="number-one-filters" class="toolbar record-filters" hidden>
        <div class="field field-grow"><label for="number-one-team">Filter team</label><input id="number-one-team" type="search" placeholder="${escapeHTML(numberOnePlaceholder)}" value="${escapeHTML(route.query.get("q") || "")}"></div>
        <div class="field"><label for="number-one-from">From date</label><div class="date-combo"><input id="number-one-from" type="text" inputmode="numeric" autocomplete="off" maxlength="10" placeholder="DD/MM/YYYY" value="${route.query.get("from") ? validDate(route.query.get("from")) : ""}" aria-describedby="number-one-from-error"><button class="button" type="button" id="number-one-from-button" aria-label="Open from-date calendar">Calendar</button><input id="number-one-from-calendar" class="native-date-proxy" type="date" min="1872-01-01" max="${summary.meta.rankings_as_of || summary.meta.results_through}" value="${escapeHTML(route.query.get("from") || "")}" tabindex="-1" aria-hidden="true"></div><span id="number-one-from-error" class="field-error" role="alert"></span></div>
        <div class="field"><label for="number-one-to">To date</label><div class="date-combo"><input id="number-one-to" type="text" inputmode="numeric" autocomplete="off" maxlength="10" placeholder="DD/MM/YYYY" value="${route.query.get("to") ? validDate(route.query.get("to")) : ""}" aria-describedby="number-one-to-error"><button class="button" type="button" id="number-one-to-button" aria-label="Open to-date calendar">Calendar</button><input id="number-one-to-calendar" class="native-date-proxy" type="date" min="1872-01-01" max="${summary.meta.rankings_as_of || summary.meta.results_through}" value="${escapeHTML(route.query.get("to") || "")}" tabindex="-1" aria-hidden="true"></div><span id="number-one-to-error" class="field-error" role="alert"></span></div>
      </div>

      <div id="record-list-filters" class="toolbar record-filters best-tournament-filters" hidden>
        <div class="field">
          <label for="record-list-team">Team</label>
          <select id="record-list-team">
            <option value="">Any team</option>
          </select>
        </div>
        <div class="field field-grow">
          <label for="record-list-competition">Competition</label>
          <input id="record-list-competition" type="search" list="record-competition-suggestions" placeholder="Competition…" value="${escapeHTML(route.query.get("competition") || "")}">
          <datalist id="record-competition-suggestions"></datalist>
        </div>
      </div>

      <div id="record-note" class="record-note"></div>
      <div id="record-table" role="tabpanel" tabindex="0" aria-live="polite"></div>
      <div class="pagination"><span id="record-count" class="muted small" aria-live="polite"></span><div class="pagination-actions"><button id="record-more" class="button">Show more</button><button id="record-all" class="button button-quiet">Show all</button></div></div>
    </div>`;

  let view = [
    "peaks",
    "numberones",
    "numberonesummary",
    "matches",
    "upsets",
    "tournaments",
  ].includes(route.query.get("view"))
    ? route.query.get("view")
    : "peaks";
  let shown = (
    Math.max(
      25,
      Number(route.query.get("shown") || 25),
    )
    || 25
  );

  const sources = {
    peaks: peakRows,
    numberones: numberOneRows,
    numberonesummary: numberOneSummaryRows,
    matches: highestMatchRows,
    upsets: upsetRows,
    tournaments: bestTournamentRows,
  };
  const peakFilters = document.getElementById(
    "peak-filters",
  );
  const numberOneFilters = document.getElementById(
    "number-one-filters",
  );
  const listFilters = document.getElementById(
    "record-list-filters",
  );
  const listTeam = document.getElementById(
    "record-list-team",
  );
  const listCompetition = document.getElementById(
    "record-list-competition",
  );
  const competitionSuggestions = document.getElementById(
    "record-competition-suggestions",
  );

  const configureListFilters = (
    preferredTeam = "",
    preserveCompetition = true,
  ) => {
    if (!pairViews.has(view)) return;
    const source = pairSources[view];
    const choices = recordTeamChoices(source, view);
    listTeam.innerHTML = (
      '<option value="">Any team</option>'
      + choices.map(
        (team) => (
          `<option value="${escapeHTML(team.code)}">`
          + `${escapeHTML(team.label)}</option>`
        ),
      ).join("")
    );
    listTeam.value = choices.some(
      (team) => team.code === preferredTeam,
    )
      ? preferredTeam
      : "";

    const competitions = recordCompetitions(source);
    listCompetition.placeholder = (
      shuffledExamples(competitions)
      || "Competition…"
    );
    competitionSuggestions.innerHTML = competitions.map(
      (competition) => (
        `<option value="${escapeHTML(competition)}"></option>`
      ),
    ).join("");
    if (!preserveCompetition) {
      listCompetition.value = "";
    }
  };

  const syncFilterVisibility = () => {
    peakFilters.hidden = view !== "peaks";
    numberOneFilters.hidden = view !== "numberones";
    listFilters.hidden = !pairViews.has(view);
  };

  configureListFilters(
    route.query.get("team") || "",
    true,
  );
  syncFilterVisibility();

  document.querySelectorAll("[data-record]").forEach(
    (button) => {
      const active = button.dataset.record === view;
      button.setAttribute("aria-pressed", String(active));
      button.setAttribute("aria-selected", String(active));
      button.tabIndex = active ? 0 : -1;
      button.classList.toggle("button-dark", active);
    },
  );

  const update = () => {
    const peakQuery = foldSearch(
      document.getElementById(
        "peak-team-search",
      ).value,
    );
    const numberOneQuery = foldSearch(
      document.getElementById(
        "number-one-team",
      ).value,
    );
    const selectedTeam = listTeam.value;
    const competitionQuery = foldSearch(
      listCompetition.value,
    );
    const fromInput = document.getElementById(
      "number-one-from",
    );
    const toInput = document.getElementById(
      "number-one-to",
    );
    const from = inputDate(fromInput.value);
    const to = inputDate(toInput.value);
    const invalidRange = Boolean(
      from && to && from > to,
    );
    const fromRangeMessage = (
      "From date cannot be after To date."
    );
    const toRangeMessage = (
      "To date cannot be before From date."
    );
    const fromError = document.getElementById(
      "number-one-from-error",
    );
    const toError = document.getElementById(
      "number-one-to-error",
    );

    if (invalidRange) {
      fromError.textContent = fromRangeMessage;
      toError.textContent = toRangeMessage;
      fromInput.setAttribute("aria-invalid", "true");
      toInput.setAttribute("aria-invalid", "true");
    } else {
      if (
        fromError.textContent === fromRangeMessage
      ) {
        fromError.textContent = "";
      }
      if (toError.textContent === toRangeMessage) {
        toError.textContent = "";
      }
      if (!fromError.textContent) {
        fromInput.removeAttribute("aria-invalid");
      }
      if (!toError.textContent) {
        toInput.removeAttribute("aria-invalid");
      }
    }

    document.getElementById(
      "number-one-from-calendar",
    ).max = to || (
      summary.meta.rankings_as_of
      || summary.meta.results_through
    );
    document.getElementById(
      "number-one-to-calendar",
    ).min = from || "1872-01-01";

    const source = sources[view].filter((row) => {
      if (view === "peaks") {
        return (
          !peakQuery
          || teamSearchText(
            row.code,
            row.nation,
            row.historical_name,
            row.display_nation,
          ).includes(peakQuery)
        );
      }

      if (view === "numberones") {
        if (invalidRange) return false;
        if (
          numberOneQuery
          && !teamSearchText(
            row.code,
            row.nation,
          ).includes(numberOneQuery)
        ) {
          return false;
        }
        const end = (
          row.to
          || summary.meta.rankings_as_of
          || summary.meta.results_through
        );
        if (from && end < from) return false;
        if (to && row.from > to) return false;
        return true;
      }

      if (view === "matches" || view === "upsets") {
        if (
          selectedTeam
          && row.code1 !== selectedTeam
          && row.code2 !== selectedTeam
        ) {
          return false;
        }
        return (
          !competitionQuery
          || foldSearch(row.tournament).includes(
            competitionQuery,
          )
        );
      }

      if (view === "tournaments") {
        if (
          selectedTeam
          && row.code !== selectedTeam
        ) {
          return false;
        }
        return (
          !competitionQuery
          || foldSearch(row.tournament).includes(
            competitionQuery,
          )
        );
      }

      return true;
    });

    const visible = source.slice(0, shown);
    document.getElementById(
      "record-note",
    ).innerHTML = view === "peaks"
      ? `<strong>Peak</strong><div><b>One maximum per canonical team lineage.</b> A peak reached under a former name shows that historical name first; a peak reached under the current name lists relevant former lineage names afterward.</div>`
      : view === "numberones"
        ? `<strong>No. 1</strong><div><b>Every spell as NFELO world number one.</b> Leadership is determined jointly after all results on each date. A result is shown only when it involved the incoming or displaced leader; otherwise the table identifies the network, inactivity or eligibility effect without attaching unrelated matches.</div>`
        : view === "numberonesummary"
          ? `<strong>Total</strong><div><b>Number-one totals use only names from actual No. 1 spells.</b> Germany includes West Germany; the Soviet Union total does not include post-Soviet Russia.</div>`
          : view === "matches"
            ? `<strong>Score</strong><div><b>Every eligible match instance is ranked.</b> Q is the two breadth-adjusted means minus 1.645 times their joint standard error; repeat pairings are not deduplicated.</div>`
            : view === "upsets"
              ? `<strong>Change</strong><div><b>Decisive results ranked by rating movement.</b> Upset points are the average of the winner's rating gain and the loser's rating loss.</div>`
              : `<strong>Gain</strong><div><b>Largest positive rating gains over one tournament edition.</b> Rating gain includes only the edition's own matchdays.</div>`;

    document.getElementById(
      "record-table",
    ).innerHTML = source.length
      ? (
        view === "peaks"
          ? peakTable(visible)
          : view === "numberones"
            ? numberOneTable(visible)
            : view === "numberonesummary"
              ? numberOneSummaryTable(visible)
              : view === "matches"
                ? matchRecordTable(visible)
                : view === "upsets"
                  ? upsetTable(visible)
                  : bestTournamentTable(visible)
      )
      : filteredEmptyState("records");

    document.getElementById(
      "record-count",
    ).textContent = (
      `Showing ${number(visible.length)} `
      + `of ${number(source.length)}`
    );
    document.getElementById(
      "record-more",
    ).hidden = shown >= source.length;
    document.getElementById(
      "record-all",
    ).hidden = shown >= source.length;

    replaceRouteQuery("records", {
      view: view === "peaks" ? "" : view,
      shown: shown > 25 ? shown : "",
      peak: view === "peaks"
        ? document.getElementById(
          "peak-team-search",
        ).value.trim()
        : "",
      q: view === "numberones"
        ? document.getElementById(
          "number-one-team",
        ).value.trim()
        : "",
      from: (
        view === "numberones" && !invalidRange
          ? from
          : ""
      ),
      to: (
        view === "numberones" && !invalidRange
          ? to
          : ""
      ),
      team: pairViews.has(view)
        ? selectedTeam
        : "",
      competition: pairViews.has(view)
        ? listCompetition.value.trim()
        : "",
    });
  };

  document.getElementById(
    "peak-team-search",
  ).addEventListener("input", () => {
    shown = 25;
    update();
  });
  document.getElementById(
    "number-one-team",
  ).addEventListener("input", () => {
    shown = 25;
    update();
  });
  listTeam.addEventListener("change", () => {
    shown = 25;
    update();
  });
  listCompetition.addEventListener("input", () => {
    shown = 25;
    update();
  });

  const setupNumberOneDate = (prefix) => {
    const input = document.getElementById(prefix);
    const calendar = document.getElementById(
      `${prefix}-calendar`,
    );
    const errorNode = document.getElementById(
      `${prefix}-error`,
    );
    const refreshIfValid = () => {
      input.value = formatHistoryDateInput(input.value);
      const error = input.value
        ? historyDateInputError(
          input.value,
          "1872-01-01",
          (
            summary.meta.rankings_as_of
            || summary.meta.results_through
          ),
        )
        : "";
      errorNode.textContent = error;
      if (error) {
        input.setAttribute("aria-invalid", "true");
      } else {
        input.removeAttribute("aria-invalid");
      }
      const complete = (
        !input.value
        || Boolean(inputDate(input.value))
      );
      if (!error && complete) {
        calendar.value = input.value
          ? inputDate(input.value)
          : "";
        shown = 25;
        update();
      }
    };
    input.addEventListener("input", refreshIfValid);
    input.addEventListener("keydown", (event) => {
      if (
        event.key === "Backspace"
        && input.selectionStart === input.selectionEnd
        && [3, 6].includes(input.selectionStart)
      ) {
        event.preventDefault();
        const position = input.selectionStart;
        input.value = (
          input.value.slice(0, position - 2)
          + input.value.slice(position)
        );
        refreshIfValid();
        input.setSelectionRange(
          position - 2,
          position - 2,
        );
      }
    });
    document.getElementById(
      `${prefix}-button`,
    ).addEventListener("click", () => {
      if (
        typeof calendar.showPicker === "function"
      ) {
        calendar.showPicker();
      } else {
        calendar.click();
      }
    });
    calendar.addEventListener("change", () => {
      input.value = calendar.value
        ? validDate(calendar.value)
        : "";
      refreshIfValid();
    });
  };
  setupNumberOneDate("number-one-from");
  setupNumberOneDate("number-one-to");

  document.querySelectorAll("[data-record]").forEach(
    (button) => button.addEventListener("click", () => {
      view = button.dataset.record;
      shown = 25;
      if (pairViews.has(view)) {
        configureListFilters("", false);
      }
      syncFilterVisibility();
      document.querySelectorAll(
        "[data-record]",
      ).forEach((peer) => {
        const active = peer === button;
        peer.setAttribute(
          "aria-pressed",
          String(active),
        );
        peer.setAttribute(
          "aria-selected",
          String(active),
        );
        peer.tabIndex = active ? 0 : -1;
        peer.classList.toggle(
          "button-dark",
          active,
        );
      });
      update();
    }),
  );

  const recordTabs = [
    ...document.querySelectorAll("[data-record]"),
  ];
  recordTabs.forEach((button, index) => {
    button.addEventListener("keydown", (event) => {
      if (
        ![
          "ArrowLeft",
          "ArrowRight",
          "Home",
          "End",
        ].includes(event.key)
      ) {
        return;
      }
      event.preventDefault();
      const nextIndex = event.key === "Home"
        ? 0
        : event.key === "End"
          ? recordTabs.length - 1
          : (
            index
            + (
              event.key === "ArrowRight"
                ? 1
                : -1
            )
            + recordTabs.length
          ) % recordTabs.length;
      recordTabs[nextIndex].focus();
      recordTabs[nextIndex].click();
    });
  });

  document.getElementById(
    "record-more",
  ).addEventListener("click", () => {
    shown += 25;
    update();
  });
  document.getElementById(
    "record-all",
  ).addEventListener("click", () => {
    shown = Number.MAX_SAFE_INTEGER;
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
    const exampleFixture = fixtures.length
      ? fixtures[Math.floor(Math.random() * fixtures.length)]
      : null;
    const fixtureSearchPlaceholder = exampleFixture
      ? `${exampleFixture.team1_name}, ${exampleFixture.team2_name}, ${exampleFixture.tournament_name}…`
      : "Team or competition…";
    content.innerHTML = `
      <div class="page">
        <header class="page-heading"><div><p class="eyebrow">Scheduled senior internationals</p><h1>Upcoming matches</h1></div><p class="lede">Validated fixtures from multiple public schedules, paired with probabilities from the current model. Individual ratings and country venue profiles are projected to the match date; Combined uses the same joint-uncertainty score as completed Matches and Records. W and L are from the perspective of the first-listed team.<span class="page-action-hint">Tap or click a probability bar for the full prediction and venue breakdown.</span></p></header>
        <div class="record-note"><strong>${number(fixtures.length)}</strong><div><b>Known future pairings.</b> Placeholder knockout matches remain hidden until both teams are identified. Feed checked ${validTimestamp(payload.checked_at)}.</div></div>
        <div class="toolbar"><div class="field field-grow"><label for="fixture-search">Team or competition</label><input id="fixture-search" type="search" placeholder="${escapeHTML(fixtureSearchPlaceholder)}" value="${escapeHTML(route.query.get("q") || "")}"></div><div class="field"><label for="fixture-competition">Competition</label><select id="fixture-competition"><option value="">All competitions</option>${competitions.map((name) => `<option value="${escapeHTML(name)}">${escapeHTML(name)}</option>`).join("")}</select></div></div>
        <p id="fixture-count" class="muted small"></p>
        <div id="fixture-table"></div>
        <div class="pagination"><span id="fixture-page" class="muted small" aria-live="polite"></span><div class="pagination-actions"><button id="fixture-more" class="button">Show more</button><button id="fixture-all" class="button button-quiet">Show all</button></div></div>
      </div>`;
    let shown = Math.max(50, Number(route.query.get("shown") || 50)) || 50;
    const requestedCompetition = route.query.get("competition") || "";
    if (competitions.includes(requestedCompetition)) document.getElementById("fixture-competition").value = requestedCompetition;
    const update = () => {
      const query = foldSearch(document.getElementById("fixture-search").value);
      const competition = document.getElementById("fixture-competition").value;
      const filtered = fixtures.filter((fixture) => {
        if (competition && fixture.tournament_name !== competition) return false;
        return !query || foldSearch([
          teamSearchText(
            fixture.team1_code,
            fixture.team1_name,
          ),
          teamSearchText(
            fixture.team2_code,
            fixture.team2_name,
          ),
          fixture.tournament_name,
        ].join(" ")).includes(query);
      });
      const visible = filtered.slice(0, shown);
      document.getElementById("fixture-count").textContent = `${number(filtered.length)} matching fixtures`;
      document.getElementById("fixture-page").textContent = `Showing ${number(visible.length)} of ${number(filtered.length)}`;
      document.getElementById("fixture-more").hidden = visible.length >= filtered.length;
      document.getElementById("fixture-all").hidden = visible.length >= filtered.length;
      document.getElementById("fixture-table").innerHTML = visible.length ? `<div class="table-shell fixture-table"><table><thead><tr><th>Date</th><th>Match</th><th>H/A/N</th><th class="numeric">Combined rating</th><th>W / D / L</th><th class="hide-mobile">Competition</th><th class="hide-mobile">Location</th></tr></thead><tbody>${visible.map((fixture) => `<tr>
        <td>${fixtureDate(fixture)}</td><td data-label="Match">${teamLink(fixture.team1_code, fixture.team1_name)} <span class="muted">v</span> ${teamLink(fixture.team2_code, fixture.team2_name)}<span class="rating-sub">${rating(fixture.rating1)} + ${rating(fixture.rating2)}</span></td><td data-label="Venue">${venueHTML(fixtureSite(fixture))}</td><td class="numeric" data-label="Combined"><span class="rating-main">${rating(fixture.combined_rating)}</span></td><td data-label="Forecast">${probabilityHTML(fixture.probabilities, {
      date: fixture.date,
      first: fixture.team1_code,
      second: fixture.team2_code,
      venue: Number(fixture.home_sign) || 0,
      matchClass: (
        fixture.friendly
          ? "friendly"
          : "competitive"
      ),
      label: (
        `Open full prediction for ${fixture.team1_name} `
        + `versus ${fixture.team2_name}`
      ),
    })}</td><td class="hide-mobile" data-label="Competition">${escapeHTML(fixture.tournament_name)}</td><td class="hide-mobile" data-label="Location">${escapeHTML([fixture.city, fixture.country].filter(Boolean).join(", "))}${fixture.neutral ? `<span class="rating-sub">neutral venue</span>` : ""}</td>
      </tr>`).join("")}</tbody></table></div>` : `<div class="empty"><h2>No fixtures match those filters.</h2></div>`;
      replaceRouteQuery("fixtures", { q: document.getElementById("fixture-search").value.trim(), competition, shown: shown > 50 ? shown : "" });
    };
    document.getElementById("fixture-search").addEventListener("input", () => { shown = 50; update(); });
    document.getElementById("fixture-competition").addEventListener("change", () => { shown = 50; update(); });
    document.getElementById("fixture-more").addEventListener("click", () => { shown += 50; update(); });
    document.getElementById("fixture-all").addEventListener("click", () => { shown = fixtures.length; update(); });
    update();
  }

  let ratingHistoryChartSequence = 0;
  const ratingHistoryChartRegistry = new Map();
  const activeRatingHistoryChartDisposers = new Set();
  const chartDay = 24 * 60 * 60 * 1000;

  const chartDateStamp = (value) => {
    const stamp = Date.parse(`${value}T00:00:00Z`);
    return Number.isFinite(stamp) ? stamp : null;
  };

  const chartPointAtOrBefore = (history, stamp) => {
    let left = 0;
    let right = history.length - 1;
    let found = null;
    while (left <= right) {
      const middle = Math.floor((left + right) / 2);
      if (history[middle].stamp <= stamp) {
        found = history[middle];
        left = middle + 1;
      } else {
        right = middle - 1;
      }
    }
    return found;
  };

  const chartNiceStep = (raw) => {
    if (!Number.isFinite(raw) || raw <= 0) return 50;
    const magnitude = 10 ** Math.floor(Math.log10(raw));
    const normalised = raw / magnitude;
    const multiple = normalised <= 1 ? 1 : normalised <= 2 ? 2 : normalised <= 5 ? 5 : 10;
    return multiple * magnitude;
  };
  const chartSeriesClass = (index) => `chart-series-${"abcdefghij"[index] || "a"}`;

  function interactiveRatingChart(series, options = {}) {
    const prepared = series.map((item, index) => ({
      label: publicTeamName(item.label),
      className: chartSeriesClass(index),
      active: item.active !== false,
      history: (item.history || [])
        .map((point) => ({
          ...point,
          rating: Number(point.rating),
          stamp: chartDateStamp(point.date),
        }))
        .filter((point) => point.stamp != null && Number.isFinite(point.rating))
        .sort((first, second) => first.stamp - second.stamp),
    }));
    const histories = prepared.map((item) => item.history).filter((history) => history.length);
    if (!histories.some((history) => history.length > 1)) {
      return `<div class="empty">A rating line begins after a team has 30 matches.</div>`;
    }
    const firstYear = Math.min(...histories.map((history) => Number(history[0].date.slice(0, 4))));
    const latestStamp = Math.max(
      ...histories.map((history) => history.at(-1).stamp),
      chartDateStamp(options.latestDate) || Number.NEGATIVE_INFINITY,
    );
    const lastYear = Math.max(
      ...histories.map((history) => Number(history.at(-1).date.slice(0, 4))),
      new Date(latestStamp).getUTCFullYear(),
    );
    const id = `rating-history-chart-${++ratingHistoryChartSequence}`;
    ratingHistoryChartRegistry.set(id, {
      series: prepared,
      firstYear,
      lastYear,
      latestStamp,
      ariaLabel: options.ariaLabel || "Rating history",
    });
    const legend = prepared.length > 1
      ? `<div class="comparison-legend" aria-label="Chart teams">${prepared.map((item, index) => `<button type="button" class="chart-legend-item" data-chart-focus-series="${index}" aria-pressed="false" ${item.history.length ? "" : `aria-disabled="true"`}><svg viewBox="0 0 28 8" aria-hidden="true"><line class="chart-legend-line ${item.className}" x1="1" y1="4" x2="27" y2="4"/></svg><span>${escapeHTML(item.label)}</span>${item.history.length ? (item.active ? "" : `<small>historical</small>`) : `<small>no rating line</small>`}</button>`).join("")}<button type="button" class="button button-quiet chart-show-all" data-chart-show-all hidden>Show all teams</button></div>`
      : "";
    return `<div class="chart-shell interactive-chart ${escapeHTML(options.className || "")}" id="${id}" data-rating-history-chart>
      ${legend}
      <div class="chart-controls">
        <form class="chart-year-form" data-chart-year-form>
          <label><span>From year</span><input type="number" inputmode="numeric" min="${firstYear}" max="${lastYear}" step="1" value="${firstYear}" data-chart-from></label>
          <label><span>To year</span><input type="number" inputmode="numeric" min="${firstYear}" max="${lastYear}" step="1" value="${lastYear}" data-chart-to></label>
          <button class="button button-quiet" type="submit">Apply years</button>
        </form>
        <div class="chart-navigation" role="group" aria-label="Move and zoom through rating history">
          <button class="button button-quiet" type="button" data-chart-earlier aria-label="Show an earlier period">← Earlier</button>
          <button class="button button-quiet" type="button" data-chart-zoom-in aria-label="Zoom in to a shorter period">＋ Zoom in</button>
          <button class="button button-quiet" type="button" data-chart-zoom-out aria-label="Zoom out to a longer period">− Zoom out</button>
          <button class="button button-quiet" type="button" data-chart-later aria-label="Show a later period">Later →</button>
          <button class="button button-quiet" type="button" data-chart-all>All years</button>
        </div>
      </div>
      <div class="chart-status">
        <span id="${id}-range" data-chart-range aria-live="polite">Showing ${yearNumber(firstYear)}–${yearNumber(lastYear)}</span>
        <span class="chart-error" data-chart-error role="alert"></span>
      </div>
      <p class="chart-help" id="${id}-help">Hover over the graph to inspect a date. Tap or click to keep a selection; use the arrow keys when the graph is focused.</p>
      <div class="chart-stage">
        <svg class="rating-chart" role="img" tabindex="0" aria-label="${escapeHTML(options.ariaLabel || "Rating history")}" aria-describedby="${id}-range ${id}-help" preserveAspectRatio="xMidYMid meet"></svg>
      </div>
      <div class="chart-inspector" data-chart-inspector aria-live="polite">
        <div class="chart-inspector-copy">
          <strong data-chart-inspector-date>Choose a date on the graph</strong>
          <span data-chart-inspector-note>Exact rating values will appear here.</span>
        </div>
        <div class="chart-inspector-values" data-chart-inspector-values></div>
        <button class="button button-quiet chart-clear" type="button" data-chart-clear hidden>Clear selection</button>
      </div>
      ${options.summary || ""}
    </div>`;
  }

  function initialiseRatingHistoryChart(shell) {
    const config = ratingHistoryChartRegistry.get(shell.id);
    if (!config) return;
    ratingHistoryChartRegistry.delete(shell.id);
    const svg = shell.querySelector(".rating-chart");
    const fromInput = shell.querySelector("[data-chart-from]");
    const toInput = shell.querySelector("[data-chart-to]");
    const rangeStatus = shell.querySelector("[data-chart-range]");
    const error = shell.querySelector("[data-chart-error]");
    const inspectorDate = shell.querySelector("[data-chart-inspector-date]");
    const inspectorNote = shell.querySelector("[data-chart-inspector-note]");
    const inspectorValues = shell.querySelector("[data-chart-inspector-values]");
    const clearButton = shell.querySelector("[data-chart-clear]");
    const earlierButton = shell.querySelector("[data-chart-earlier]");
    const laterButton = shell.querySelector("[data-chart-later]");
    const zoomInButton = shell.querySelector("[data-chart-zoom-in]");
    const zoomOutButton = shell.querySelector("[data-chart-zoom-out]");
    const allButton = shell.querySelector("[data-chart-all]");
    const legendButtons = [...shell.querySelectorAll("[data-chart-focus-series]")];
    const showAllTeamsButton = shell.querySelector("[data-chart-show-all]");
    let fromYear = config.firstYear;
    let toYear = config.lastYear;
    let geometry = null;
    let selectedStamp = null;
    let pinned = false;
    let focusedSeries = null;
    let lastDrawnWidth = 0;

    const rangeStamps = () => ({
      start: Date.UTC(fromYear, 0, 1),
      end: toYear === config.lastYear
        ? config.latestStamp
        : Date.UTC(toYear, 11, 31),
    });

    const resetInspector = () => {
      selectedStamp = null;
      pinned = false;
      const crosshair = svg.querySelector("[data-chart-crosshair]");
      const markers = svg.querySelector("[data-chart-markers]");
      if (crosshair) crosshair.hidden = true;
      if (markers) markers.innerHTML = "";
      inspectorDate.textContent = "Choose a date on the graph";
      inspectorNote.textContent = "Exact rating values will appear here.";
      inspectorValues.innerHTML = "";
      clearButton.hidden = true;
    };

    const inspect = (rawStamp, keep = pinned) => {
      if (!geometry) return;
      const stamp = Math.max(geometry.start, Math.min(geometry.end, Math.round(rawStamp / chartDay) * chartDay));
      selectedStamp = stamp;
      pinned = keep;
      const xPosition = geometry.x(stamp);
      const crosshair = svg.querySelector("[data-chart-crosshair]");
      const markers = svg.querySelector("[data-chart-markers]");
      crosshair.hidden = false;
      crosshair.setAttribute("x1", xPosition);
      crosshair.setAttribute("x2", xPosition);
      const selectedDate = new Date(stamp).toISOString().slice(0, 10);
      inspectorDate.textContent = validDate(selectedDate);
      inspectorNote.textContent = pinned
        ? "Selection fixed. Tap or click another position to move it."
        : "Rating at the end of this date.";
      const inspected = config.series.map((item, index) => {
        const point = chartPointAtOrBefore(item.history, stamp);
        const ended = Boolean(
          point
          && !item.active
          && stamp > item.history.at(-1).stamp
        );
        return { item, index, point, ended };
      }).sort((first, second) => (
        Number(Boolean(second.point)) - Number(Boolean(first.point))
        || (second.point?.rating ?? Number.NEGATIVE_INFINITY)
          - (first.point?.rating ?? Number.NEGATIVE_INFINITY)
        || first.index - second.index
      ));
      const values = inspected.map(({ item, point, ended }) => {
        if (!point) {
          const unavailable = item.history.length
            ? "Not yet eligible for a rating"
            : "No rating line (fewer than 30 matches)";
          return `<span class="chart-inspector-value ${item.className}"><i></i><span><b>${escapeHTML(item.label)}</b><small>${unavailable}</small></span><strong>—</strong></span>`;
        }
        const displayLabel = publicTeamName(point.historical_name || item.label);
        const lineage = displayLabel === item.label
          ? ""
          : `${item.label} history · `;
        const note = ended
          ? `${lineage}No longer active · final change ${validDate(point.date)}`
          : `${lineage}Last changed ${validDate(point.date)}`;
        return `<span class="chart-inspector-value ${item.className}"><i></i><span><b>${escapeHTML(displayLabel)}</b><small>${escapeHTML(note)}</small></span><strong>${rating(point.rating)}</strong></span>`;
      });
      inspectorValues.innerHTML = values.join("");
      markers.innerHTML = config.series.map((item, index) => {
        const point = chartPointAtOrBefore(item.history, stamp);
        const ended = Boolean(
          point
          && !item.active
          && stamp > item.history.at(-1).stamp
        );
        const focusClass = focusedSeries == null
          ? ""
          : index === focusedSeries ? " is-focused" : " is-dimmed";
        return point && !ended
          ? `<circle class="chart-marker ${item.className}${focusClass}" cx="${xPosition}" cy="${geometry.y(point.rating)}" r="5"/>`
          : "";
      }).join("");
      clearButton.hidden = false;
    };

    const draw = () => {
      const bounds = svg.getBoundingClientRect();
      const width = Math.max(280, Math.round(bounds.width || shell.clientWidth || 1000));
      const height = Math.max(280, Math.round(bounds.height || 360));
      lastDrawnWidth = width;
      const compact = width < 600;
      const pad = {
        left: compact ? 48 : 62,
        right: compact ? 12 : 20,
        top: 20,
        bottom: 38,
      };
      const { start, end } = rangeStamps();
      const plotWidth = width - pad.left - pad.right;
      const plotHeight = height - pad.top - pad.bottom;
      const x = (stamp) => pad.left + (stamp - start) / Math.max(chartDay, end - start) * plotWidth;
      const samples = config.series.flatMap((item) => {
        if (!item.history.length) return [];
        const finalStamp = item.history.at(-1).stamp;
        if (!item.active && finalStamp < start) return [];
        const seriesEnd = item.active ? end : Math.min(end, finalStamp);
        const before = chartPointAtOrBefore(item.history, start);
        const within = item.history.filter((point) => point.stamp > start && point.stamp <= seriesEnd);
        return before ? [before, ...within] : within;
      });
      const ratings = samples.map((point) => point.rating);
      const rawMin = Math.min(...ratings);
      const rawMax = Math.max(...ratings);
      const rawSpan = Math.max(40, rawMax - rawMin);
      const yStep = chartNiceStep(rawSpan / 4);
      let minY = Math.floor((rawMin - yStep * 0.45) / yStep) * yStep;
      let maxY = Math.ceil((rawMax + yStep * 0.45) / yStep) * yStep;
      if (maxY <= minY) maxY = minY + yStep;
      const y = (value) => height - pad.bottom - (value - minY) / (maxY - minY) * plotHeight;
      const yTicks = [];
      for (let tick = minY; tick <= maxY + yStep / 2; tick += yStep) yTicks.push(tick);
      const yearSpan = toYear - fromYear;
      const xTickCount = Math.min(yearSpan + 1, compact ? 4 : width < 850 ? 5 : 6);
      const xTicks = xTickCount <= 1
        ? [fromYear]
        : [...new Set(Array.from({ length: xTickCount }, (_, index) => (
          Math.round(fromYear + yearSpan * index / (xTickCount - 1))
        )))];
      const stepPath = (item) => {
        if (!item.history.length) return "";
        const finalStamp = item.history.at(-1).stamp;
        const seriesEnd = item.active ? end : Math.min(end, finalStamp);
        if (seriesEnd < start) return "";
        let current = chartPointAtOrBefore(item.history, start);
        let path = current ? `M ${x(start).toFixed(2)} ${y(current.rating).toFixed(2)}` : "";
        item.history.filter((point) => point.stamp > start && point.stamp <= seriesEnd).forEach((point) => {
          if (current) {
            path += ` H ${x(point.stamp).toFixed(2)} V ${y(point.rating).toFixed(2)}`;
          } else {
            path = `M ${x(point.stamp).toFixed(2)} ${y(point.rating).toFixed(2)}`;
          }
          current = point;
        });
        if (current) path += ` H ${x(seriesEnd).toFixed(2)}`;
        return path;
      };
      const clipId = `${shell.id}-clip`;
      svg.setAttribute("viewBox", `0 0 ${width} ${height}`);
      svg.innerHTML = `
        <title>${escapeHTML(config.ariaLabel)}</title>
        <desc>Step chart of ratings after eligible matches. Use the year controls to zoom or move through time, then hover, tap or use the keyboard to inspect exact values.</desc>
        <defs><clipPath id="${clipId}"><rect x="${pad.left}" y="${pad.top}" width="${plotWidth}" height="${plotHeight}"/></clipPath></defs>
        <g aria-hidden="true">
          ${yTicks.map((tick) => `<line class="grid" x1="${pad.left}" y1="${y(tick)}" x2="${width - pad.right}" y2="${y(tick)}"/><text x="${pad.left - 8}" y="${y(tick) + 4}" text-anchor="end">${rating(tick)}</text>`).join("")}
          ${xTicks.map((year) => `<text x="${x(Date.UTC(year, 6, 2))}" y="${height - 10}" text-anchor="middle">${yearNumber(year)}</text>`).join("")}
          <g clip-path="url(#${clipId})">
            ${config.series.map((item, index) => {
              const path = stepPath(item);
              const focusClass = focusedSeries == null
                ? ""
                : index === focusedSeries ? " is-focused" : " is-dimmed";
              return path ? `<path class="rating-history-line ${item.className}${focusClass}" d="${path}"/>` : "";
            }).join("")}
            <line class="chart-crosshair" data-chart-crosshair x1="0" y1="${pad.top}" x2="0" y2="${height - pad.bottom}" hidden/>
            <g data-chart-markers></g>
          </g>
          <rect class="chart-hit-area" x="${pad.left}" y="${pad.top}" width="${plotWidth}" height="${plotHeight}" data-chart-hit-area/>
        </g>`;
      geometry = { start, end, x, y, width, pad };
      if (selectedStamp == null) {
        resetInspector();
      } else {
        inspect(selectedStamp, pinned);
      }
      rangeStatus.textContent = focusedSeries == null
        ? `Showing ${yearNumber(fromYear)}–${yearNumber(toYear)}`
        : `Showing ${yearNumber(fromYear)}–${yearNumber(toYear)} · highlighting ${config.series[focusedSeries].label}`;
      fromInput.value = fromYear;
      toInput.value = toYear;
      const fullRange = fromYear === config.firstYear && toYear === config.lastYear;
      earlierButton.disabled = fromYear <= config.firstYear;
      laterButton.disabled = toYear >= config.lastYear;
      zoomInButton.disabled = fromYear === toYear;
      zoomOutButton.disabled = fullRange;
      allButton.disabled = fullRange;
    };

    const setRange = (nextFrom, nextTo) => {
      fromYear = Math.max(config.firstYear, Math.min(config.lastYear, Math.round(nextFrom)));
      toYear = Math.max(fromYear, Math.min(config.lastYear, Math.round(nextTo)));
      error.textContent = "";
      resetInspector();
      draw();
    };

    const applyYears = () => {
      const nextFrom = Number(fromInput.value);
      const nextTo = Number(toInput.value);
      if (!Number.isInteger(nextFrom) || !Number.isInteger(nextTo)) {
        error.textContent = "Enter complete four-digit years.";
        return;
      }
      if (nextFrom < config.firstYear || nextFrom > config.lastYear || nextTo < config.firstYear || nextTo > config.lastYear) {
        error.textContent = `Choose years from ${yearNumber(config.firstYear)} to ${yearNumber(config.lastYear)}.`;
        return;
      }
      if (nextFrom > nextTo) {
        error.textContent = "From year cannot be after To year.";
        return;
      }
      setRange(nextFrom, nextTo);
    };

    const zoom = (direction) => {
      const totalYears = config.lastYear - config.firstYear + 1;
      const visibleYears = toYear - fromYear + 1;
      const targetYears = direction < 0
        ? Math.max(1, Math.ceil(visibleYears / 2))
        : Math.min(totalYears, visibleYears * 2);
      const centre = (fromYear + toYear) / 2;
      let nextFrom = Math.round(centre - (targetYears - 1) / 2);
      let nextTo = nextFrom + targetYears - 1;
      if (nextFrom < config.firstYear) {
        nextFrom = config.firstYear;
        nextTo = nextFrom + targetYears - 1;
      }
      if (nextTo > config.lastYear) {
        nextTo = config.lastYear;
        nextFrom = nextTo - targetYears + 1;
      }
      setRange(nextFrom, nextTo);
    };

    const move = (direction) => {
      const span = toYear - fromYear;
      const distance = Math.max(1, Math.round((span + 1) / 2));
      let nextFrom = fromYear + direction * distance;
      let nextTo = toYear + direction * distance;
      if (nextFrom < config.firstYear) {
        nextFrom = config.firstYear;
        nextTo = nextFrom + span;
      }
      if (nextTo > config.lastYear) {
        nextTo = config.lastYear;
        nextFrom = nextTo - span;
      }
      setRange(nextFrom, nextTo);
    };

    const stampFromClientX = (clientX) => {
      const bounds = svg.getBoundingClientRect();
      const viewX = (clientX - bounds.left) / Math.max(1, bounds.width) * geometry.width;
      const clampedX = Math.max(geometry.pad.left, Math.min(geometry.width - geometry.pad.right, viewX));
      return geometry.start + (clampedX - geometry.pad.left) / (geometry.width - geometry.pad.left - geometry.pad.right) * (geometry.end - geometry.start);
    };

    shell.querySelector("[data-chart-year-form]").addEventListener("submit", (event) => {
      event.preventDefault();
      applyYears();
    });
    earlierButton.addEventListener("click", () => move(-1));
    laterButton.addEventListener("click", () => move(1));
    zoomInButton.addEventListener("click", () => zoom(-1));
    zoomOutButton.addEventListener("click", () => zoom(1));
    allButton.addEventListener("click", () => setRange(config.firstYear, config.lastYear));
    const focusOnSeries = (index) => {
      if (!config.series[index]?.history.length) return;
      focusedSeries = focusedSeries === index ? null : index;
      legendButtons.forEach((button, buttonIndex) => {
        button.setAttribute("aria-pressed", String(buttonIndex === focusedSeries));
      });
      if (showAllTeamsButton) showAllTeamsButton.hidden = focusedSeries == null;
      draw();
    };
    legendButtons.forEach((button, index) => {
      button.addEventListener("click", () => focusOnSeries(index));
    });
    showAllTeamsButton?.addEventListener("click", () => {
      focusedSeries = null;
      legendButtons.forEach((button) => button.setAttribute("aria-pressed", "false"));
      showAllTeamsButton.hidden = true;
      draw();
    });
    clearButton.addEventListener("click", resetInspector);
    svg.addEventListener("pointermove", (event) => {
      if ((!event.pointerType || event.pointerType === "mouse") && !pinned) inspect(stampFromClientX(event.clientX), false);
    });
    svg.addEventListener("pointerleave", () => {
      if (!pinned) resetInspector();
    });
    svg.addEventListener("click", (event) => {
      if (event.detail === 0) return;
      inspect(stampFromClientX(event.clientX), true);
    });
    svg.addEventListener("keydown", (event) => {
      if (!["ArrowLeft", "ArrowRight", "Home", "End", "Escape"].includes(event.key)) return;
      event.preventDefault();
      if (event.key === "Escape") {
        resetInspector();
        return;
      }
      const { start, end } = rangeStamps();
      const stamps = [...new Set([
        start,
        ...config.series.flatMap((item) => item.history
          .filter((point) => point.stamp >= start && point.stamp <= end)
          .map((point) => point.stamp)),
        end,
      ])].sort((first, second) => first - second);
      let index = selectedStamp == null
        ? (event.key === "ArrowLeft" || event.key === "End" ? stamps.length - 1 : 0)
        : stamps.reduce((best, stamp, candidate) => (
          Math.abs(stamp - selectedStamp) < Math.abs(stamps[best] - selectedStamp) ? candidate : best
        ), 0);
      if (event.key === "Home") index = 0;
      if (event.key === "End") index = stamps.length - 1;
      if (event.key === "ArrowLeft" && selectedStamp != null) index = Math.max(0, index - 1);
      if (event.key === "ArrowRight" && selectedStamp != null) index = Math.min(stamps.length - 1, index + 1);
      inspect(stamps[index], true);
    });

    draw();
    let resizeObserver = null;
    let resizeHandler = null;
    if (typeof ResizeObserver === "function") {
      resizeObserver = new ResizeObserver((entries) => {
        const nextWidth = Math.round(entries[0]?.contentRect.width || 0);
        if (nextWidth && Math.abs(nextWidth - lastDrawnWidth) > 2) draw();
      });
      resizeObserver.observe(svg);
    } else {
      resizeHandler = () => draw();
      window.addEventListener("resize", resizeHandler);
    }
    const dispose = () => {
      resizeObserver?.disconnect();
      if (resizeHandler) window.removeEventListener("resize", resizeHandler);
      activeRatingHistoryChartDisposers.delete(dispose);
    };
    activeRatingHistoryChartDisposers.add(dispose);
  }

  function initialiseRatingHistoryCharts(root) {
    root.querySelectorAll("[data-rating-history-chart]").forEach(initialiseRatingHistoryChart);
  }

  function disposeRatingHistoryCharts() {
    [...activeRatingHistoryChartDisposers].forEach((dispose) => dispose());
  }

  const MAX_COMPARISON_TEAMS = 10;

  function comparisonChart(pages, teams) {
    return interactiveRatingChart(teams.map((team, index) => ({
      label: team.nation,
      history: pages[index].history,
      active: Boolean(team.rank),
    })), {
      className: "comparison-chart",
      latestDate: teams.some((team) => team.rank)
        ? summary.meta.results_through
        : "",
      ariaLabel: `Rating histories for ${teams.map((team) => team.nation).join(", ")}`,
    });
  }

  async function renderCompare(route) {
    setTitle("Compare teams");
    const allTeams = summary.teams;
    const currentTeams = summary.current;
    const teamByCode = new Map(allTeams.map((team) => [team.code, team]));
    const validCodes = new Set(teamByCode.keys());
    const uniqueValidCodes = (values) => [...new Set(values)]
      .filter((code) => validCodes.has(code))
      .slice(0, MAX_COMPARISON_TEAMS);
    const requestedTeams = uniqueValidCodes(
      (route.query.get("teams") || "")
        .split(",")
        .map((value) => value.trim())
        .filter(Boolean),
    );
    if (!requestedTeams.length) {
      requestedTeams.push(...uniqueValidCodes([
        route.query.get("a"),
        route.query.get("b"),
      ].filter(Boolean)));
    }
    currentTeams.forEach((team) => {
      if (requestedTeams.length < 2 && !requestedTeams.includes(team.code)) {
        requestedTeams.push(team.code);
      }
    });
    let selectedCodes = requestedTeams.slice(0, MAX_COMPARISON_TEAMS);
    let pairCodes = uniqueValidCodes(
      (route.query.get("pair") || "")
        .split(",")
        .map((value) => value.trim())
        .filter(Boolean),
    ).filter((code) => selectedCodes.includes(code)).slice(0, 2);
    let addingTeam = false;
    let drawVersion = 0;
    let pairVersion = 0;
    let comparisonPages = new Map();
    const resultsYear = Number(summary.meta.results_through.slice(0, 4));

    const ensurePair = () => {
      pairCodes = [...new Set([
        ...pairCodes.filter((code) => selectedCodes.includes(code)),
        ...selectedCodes,
      ])].slice(0, 2);
    };
    ensurePair();

    const comparisonStatus = (team) => {
      if (team.rank) return `Current world no. ${number(team.rank)}`;
      return resultsYear - Number(team.last_year) > 4
        ? `Historical · last active ${yearNumber(team.last_year)}`
        : `Currently unranked · last active ${yearNumber(team.last_year)}`;
    };
    const comparisonRatingLabel = (team) => {
      if (team.rank) return "Current rating";
      return resultsYear - Number(team.last_year) > 4
        ? "Final rating"
        : "Latest rating";
    };
    const optionGroups = (selectedCode = "", placeholder = false) => {
      const blocked = new Set(selectedCodes.filter((code) => code !== selectedCode));
      const option = (team) => {
        const context = team.rank
          ? `No. ${number(team.rank)} · ${rating(team.rating)}`
          : `last active ${yearNumber(team.last_year)} · ${rating(team.rating)}`;
        return `<option value="${escapeHTML(team.code)}" ${team.code === selectedCode ? "selected" : ""} ${blocked.has(team.code) ? "disabled" : ""}>${escapeHTML(team.nation)} · ${context}</option>`;
      };
      return `${placeholder ? `<option value="" selected>Choose a team…</option>` : ""}
        <optgroup label="Currently ranked">${currentTeams.map(option).join("")}</optgroup>
        <optgroup label="Historical or currently unranked">${allTeams.filter((team) => !team.rank).map(option).join("")}</optgroup>`;
    };
    const writeURL = () => {
      replaceRouteQuery("compare", {
        teams: selectedCodes.join(","),
        pair: pairCodes.join(","),
      });
    };

    content.innerHTML = `
      <div class="page comparison-page">
        <header class="page-heading"><div><p class="eyebrow">Current and historical teams</p><h1>Compare teams</h1></div><p class="lede">Compare between two and ten national teams across their complete rating histories, then inspect any selected pair’s head-to-head record.</p></header>
        <section class="comparison-selection" aria-labelledby="comparison-selection-title">
          <div class="section-heading compact-heading"><div><p class="eyebrow">2–10 teams</p><h2 id="comparison-selection-title">Teams in this comparison</h2></div><span class="muted small" id="comparison-team-count"></span></div>
          <div id="comparison-picker"></div>
        </section>
        <div id="comparison-output"></div>
      </div>`;
    const picker = document.getElementById("comparison-picker");
    const output = document.getElementById("comparison-output");

    const renderPicker = () => {
      document.getElementById("comparison-team-count").textContent = `${number(selectedCodes.length)} of ${MAX_COMPARISON_TEAMS} selected`;
      picker.innerHTML = `
        <div class="comparison-team-list">
          ${selectedCodes.map((code, index) => {
            const team = teamByCode.get(code);
            return `<div class="comparison-team-row">
              <i class="comparison-series-swatch ${chartSeriesClass(index)}" aria-hidden="true"></i>
              <label><span>Team ${index + 1}</span><select data-comparison-team="${index}" aria-label="Team ${index + 1}">${optionGroups(code)}</select></label>
              ${selectedCodes.length > 2 ? `<button class="button button-quiet comparison-remove" type="button" data-comparison-remove="${index}" aria-label="Remove ${escapeHTML(team.nation)}">Remove</button>` : ""}
            </div>`;
          }).join("")}
        </div>
        <div class="comparison-add-area">
          <button class="button button-quiet" id="comparison-add-toggle" type="button" ${selectedCodes.length >= MAX_COMPARISON_TEAMS ? "disabled" : ""}>＋ Add another team <span>${selectedCodes.length}/${MAX_COMPARISON_TEAMS}</span></button>
          ${addingTeam && selectedCodes.length < MAX_COMPARISON_TEAMS ? `<div class="comparison-add-panel">
            <label for="comparison-new-team"><span>Current or historical team</span><select id="comparison-new-team">${optionGroups("", true)}</select></label>
            <button class="button button-dark" id="comparison-add-confirm" type="button" disabled>Add selected team</button>
            <button class="button button-quiet" id="comparison-add-cancel" type="button">Cancel</button>
          </div>` : ""}
        </div>`;
      picker.querySelectorAll("[data-comparison-team]").forEach((select) => {
        select.addEventListener("change", () => {
          const index = Number(select.dataset.comparisonTeam);
          const previous = selectedCodes[index];
          const replacement = select.value;
          if (!validCodes.has(replacement) || selectedCodes.some((code, candidate) => code === replacement && candidate !== index)) return;
          selectedCodes[index] = replacement;
          pairCodes = pairCodes.map((code) => code === previous ? replacement : code);
          ensurePair();
          addingTeam = false;
          renderPicker();
          void refreshComparison();
        });
      });
      picker.querySelectorAll("[data-comparison-remove]").forEach((button) => {
        button.addEventListener("click", () => {
          if (selectedCodes.length <= 2) return;
          const [removed] = selectedCodes.splice(Number(button.dataset.comparisonRemove), 1);
          pairCodes = pairCodes.filter((code) => code !== removed);
          ensurePair();
          addingTeam = false;
          renderPicker();
          void refreshComparison();
        });
      });
      document.getElementById("comparison-add-toggle")?.addEventListener("click", () => {
        addingTeam = true;
        renderPicker();
        document.getElementById("comparison-new-team")?.focus();
      });
      const newTeam = document.getElementById("comparison-new-team");
      const confirm = document.getElementById("comparison-add-confirm");
      newTeam?.addEventListener("change", () => {
        confirm.disabled = !validCodes.has(newTeam.value) || selectedCodes.includes(newTeam.value);
      });
      confirm?.addEventListener("click", () => {
        if (!validCodes.has(newTeam.value) || selectedCodes.includes(newTeam.value) || selectedCodes.length >= MAX_COMPARISON_TEAMS) return;
        selectedCodes.push(newTeam.value);
        addingTeam = false;
        renderPicker();
        void refreshComparison();
      });
      document.getElementById("comparison-add-cancel")?.addEventListener("click", () => {
        addingTeam = false;
        renderPicker();
      });
    };

    const pairOptions = (selected, blocked) => selectedCodes.map((code) => {
      const team = teamByCode.get(code);
      return `<option value="${escapeHTML(code)}" ${code === selected ? "selected" : ""} ${code === blocked ? "disabled" : ""}>${escapeHTML(team.nation)}</option>`;
    }).join("");

    const renderPairControls = () => {
      const pairPicker = document.getElementById("comparison-pair-picker");
      if (!pairPicker) return;
      pairPicker.innerHTML = `
        <div class="team-picker"><label for="comparison-pair-a">First team</label><select id="comparison-pair-a">${pairOptions(pairCodes[0], pairCodes[1])}</select></div>
        <button class="button button-quiet comparison-swap" id="comparison-pair-swap" type="button" aria-label="Swap head-to-head perspective">⇄ Swap</button>
        <div class="team-picker"><label for="comparison-pair-b">Second team</label><select id="comparison-pair-b">${pairOptions(pairCodes[1], pairCodes[0])}</select></div>`;
      document.getElementById("comparison-pair-a").addEventListener("change", (event) => {
        pairCodes[0] = event.target.value;
        ensurePair();
        writeURL();
        renderPairControls();
        void renderHeadToHead();
      });
      document.getElementById("comparison-pair-b").addEventListener("change", (event) => {
        pairCodes[1] = event.target.value;
        ensurePair();
        writeURL();
        renderPairControls();
        void renderHeadToHead();
      });
      document.getElementById("comparison-pair-swap").addEventListener("click", () => {
        [pairCodes[0], pairCodes[1]] = [pairCodes[1], pairCodes[0]];
        writeURL();
        renderPairControls();
        void renderHeadToHead();
      });
    };

    const renderHeadToHead = async () => {
      const version = ++pairVersion;
      const headOutput = document.getElementById("comparison-head-to-head");
      if (!headOutput) return;
      const codeA = pairCodes[0];
      const codeB = pairCodes[1];
      const a = teamByCode.get(codeA);
      const b = teamByCode.get(codeB);
      headOutput.innerHTML = `<div class="loading-shell compact-loading" role="status"><span class="spinner" aria-hidden="true"></span><p>Loading ${escapeHTML(a.nation)} and ${escapeHTML(b.nation)}…</p></div>`;
      const first = await getJSON(`data/teams/${encodeURIComponent(codeA)}.json`);
      if (version !== pairVersion || !document.getElementById("comparison-head-to-head")) return;
      const meetings = first.matches.filter((match) => match.opponent_code === codeB);
      const head = meetings.reduce((row, match) => {
        row[match.result] += 1;
        row.gf += match.gf;
        row.ga += match.ga;
        return row;
      }, { W: 0, D: 0, L: 0, gf: 0, ga: 0 });
      const bothCurrent = Boolean(a.rank && b.rank);
      const commonDate = [codeA, codeB]
        .map((code) => comparisonPages.get(code)?.history.at(-1)?.date)
        .filter(Boolean)
        .sort()[0] || summary.meta.results_through;
      const predictionLink = bothCurrent
        ? `#/predict?a=${encodeURIComponent(codeA)}&b=${encodeURIComponent(codeB)}`
        : predictURL({
          date: commonDate,
          first: codeA,
          second: codeB,
          venue: 0,
          matchClass: "competitive",
        });
      headOutput.innerHTML = `
        <div class="comparison-head-summary">
          <strong>${escapeHTML(a.nation)}: ${head.W} wins · ${head.D} draws · ${head.L} losses · goals ${head.gf}–${head.ga}</strong>
          <a class="button button-dark" href="${predictionLink}">${bothCurrent ? "Open current prediction" : `Open historical prediction at ${validDate(commonDate)}`} →</a>
        </div>
        ${meetings.length ? `<div class="table-hint" aria-hidden="true">Swipe horizontally to see all columns →</div><div class="table-shell comparison-meetings"><table><thead><tr><th>Date</th><th>Match</th><th>H/A/N</th><th>Result</th><th>Competition</th></tr></thead><tbody>${meetings.map((match) => `<tr><td data-label="Date">${validDate(match.date)}</td><td data-label="Match">${escapeHTML(match.team_name)} <span class="score">${match.gf}–${match.ga}</span> ${teamLink(match.opponent_code, match.opponent, match.date)}</td><td data-label="Venue">${venueHTML(match.site)}</td><td data-label="Result">${formHTML([match.result])}</td><td data-label="Competition">${escapeHTML(match.tournament)}</td></tr>`).join("")}</tbody></table></div>` : `<div class="empty"><h3>No recorded meetings</h3><p>${escapeHTML(a.nation)} and ${escapeHTML(b.nation)} have not met in the results database.</p></div>`}`;
    };

    const drawComparison = async () => {
      const version = ++drawVersion;
      pairVersion += 1;
      disposeRatingHistoryCharts();
      ensurePair();
      writeURL();
      output.innerHTML = `<div class="loading-shell" role="status"><span class="spinner" aria-hidden="true"></span><p>Loading ${number(selectedCodes.length)} rating histories…</p></div>`;
      const codes = [...selectedCodes];
      const pages = await Promise.all(codes.map((code) => (
        getJSON(`data/comparison/${encodeURIComponent(code)}.json`)
      )));
      if (version !== drawVersion) return;
      comparisonPages = new Map(pages.map((page) => [page.code, page]));
      const teams = codes.map((code) => teamByCode.get(code));
      output.innerHTML = `
        <section class="section comparison-summary-section">
          <div class="section-heading"><div><p class="eyebrow">${number(teams.length)} selected teams</p><h2>Comparison summary</h2></div></div>
          <div class="table-shell comparison-summary-table"><table><thead><tr><th>Team</th><th>Status</th><th class="numeric">Rating</th><th>12-month movement</th><th>Home/away effect</th><th>All-time peak</th><th>Overall record</th></tr></thead><tbody>
            ${teams.map((team, index) => `<tr>
              <td data-label="Team"><span class="comparison-team-name"><i class="comparison-series-swatch ${chartSeriesClass(index)}" aria-hidden="true"></i>${teamLink(team.code, team.nation)}</span></td>
              <td data-label="Status">${comparisonStatus(team)}</td>
              <td class="numeric" data-label="${comparisonRatingLabel(team)}"><span class="rating-main">${rating(team.rating)}</span><span class="rating-sub">${comparisonRatingLabel(team)}</span></td>
              <td data-label="12-month movement">${team.rank ? movementHTML(team) : "—"}</td>
              <td data-label="Home/away effect">${compactVenueProfileHTML(team.venue_effect)}</td>
              <td data-label="All-time peak">${team.peak ? `${rating(team.peak.rating)}<span class="rating-sub">${validDate(team.peak.date)}</span>` : "—"}</td>
              <td data-label="Overall record">${number(team.wins)}–${number(team.draws)}–${number(team.losses)}</td>
            </tr>`).join("")}
          </tbody></table></div>
        </section>
        <section class="section"><div class="section-heading"><div><p class="eyebrow">After every eligible match</p><h2>Rating histories</h2></div><p class="muted small">Select a team in the legend to highlight its line.</p></div>${comparisonChart(pages, teams)}</section>
        <section class="section comparison-head-section">
          <div class="section-heading"><div><p class="eyebrow">Choose any two selected teams</p><h2>Head to head</h2></div></div>
          <div class="comparison-pair-picker" id="comparison-pair-picker"></div>
          <div id="comparison-head-to-head"></div>
        </section>`;
      initialiseRatingHistoryCharts(output);
      renderPairControls();
      await renderHeadToHead();
    };
    const refreshComparison = async () => {
      try {
        await drawComparison();
      } catch (error) {
        console.error(error);
        output.innerHTML = `<div class="error-panel" role="alert"><h2>The comparison could not be loaded.</h2><p>${escapeHTML(error.message)}</p><button class="button button-dark" type="button" id="comparison-retry">Retry</button></div>`;
        document.getElementById("comparison-retry")?.addEventListener("click", () => { void refreshComparison(); });
      }
    };

    renderPicker();
    await refreshComparison();
  }

  const modelValueForYear = (year, values) => {
    const knots = summary.parameters.knot_years;
    if (year <= knots[0]) return Number(values[0]);
    if (year >= knots[knots.length - 1]) return Number(values[values.length - 1]);
    const right = knots.findIndex((knot) => year <= knot);
    const fraction = (year - knots[right - 1]) / (knots[right] - knots[right - 1]);
    return Number(values[right - 1]) + fraction * (Number(values[right]) - Number(values[right - 1]));
  };
  const historicalScale = (year) => Math.exp(modelValueForYear(year, summary.parameters.calibration_scale.map(Math.log)));
  const historicalHome = (year) => modelValueForYear(year, summary.parameters.home_advantage);
  const historicalDraw = (year) => {
    const transformed = summary.parameters.draw_probability.map((value) => {
      const unit = (value - 0.05) / 0.40;
      return Math.log(unit / (1 - unit));
    });
    const logit = modelValueForYear(year, transformed);
    return 0.05 + 0.40 / (1 + Math.exp(-logit));
  };
  const poissonMasses = (lambda, maximum = 40) => {
    const values = [Math.exp(-lambda)];
    for (let goals = 1; goals <= maximum; goals += 1) values.push(values[goals - 1] * lambda / goals);
    return values;
  };
  const marginWeight = (margin, environment) => {
    const parameters = summary.parameters.goal_margin;
    if (margin === 0) return parameters.draw;
    const raw = Math.min(Math.abs(margin), 7);
    let effective = 1 + (raw - 1) * Math.pow(1.10 / Math.max(0.10, environment), parameters.environment_power);
    effective = Math.min(7, effective);
    if (effective <= 1) return 1;
    if (effective <= 2) return 1 + (effective - 1) * (parameters.two - 1);
    if (effective <= 3) return parameters.two + (effective - 2) * (parameters.three - parameters.two);
    return parameters.three + parameters.tail * (effective - 3);
  };

  async function renderPredict(route = { query: new URLSearchParams() }) {
    setTitle("Predict a match");
    loading("Loading prediction history…");
    const [historyIndex, currentState, fixturePayload] = await Promise.all([
      getJSON("data/rankings-history/index.json"),
      getJSON("data/state.json"),
      getJSON("data/fixtures.json"),
    ]);
    const today = todayISO();
    const latestFixtureDate = (fixturePayload.fixtures || []).reduce(
      (latest, fixture) => (
        String(fixture.date) > latest
          ? String(fixture.date)
          : latest
      ),
      today,
    );
    const maximumPredictionDate = (
      latestFixtureDate > today
        ? latestFixtureDate
        : today
    );
    const requested = isoDate(route.query.get("date")) || today;
    let selectedDate = requested < historyIndex.first
      ? historyIndex.first
      : requested > maximumPredictionDate
        ? maximumPredictionDate
        : requested;
    content.innerHTML = `
      <div class="page predict-page">
        <header class="page-heading"><div><p class="eyebrow">Historical and current match calculator</p><h1>Predict a match</h1></div><p class="lede">Choose any date and two teams ranked on that date. The main forecast shows W/D/L probabilities; exact scores and projected rating effects remain available in expandable tables.</p></header>
        ${ratingForecastExplanation()}
        <div class="toolbar history-toolbar predict-date-toolbar">
          <div class="history-date-actions"><div class="field history-date-field"><label for="predict-date">Prediction date</label><div class="date-combo"><input id="predict-date" type="text" inputmode="numeric" autocomplete="off" maxlength="10" placeholder="DD/MM/YYYY" value="${validDate(selectedDate)}" aria-describedby="predict-date-error"><button class="button" type="button" id="predict-calendar-button" aria-label="Open prediction-date calendar">Calendar</button><input id="predict-calendar" class="native-date-proxy" type="date" min="${historyIndex.first}" max="${maximumPredictionDate}" value="${selectedDate}" tabindex="-1" aria-hidden="true"></div><span id="predict-date-error" class="field-error" role="alert"></span></div><button class="button button-dark" type="button" id="predict-apply">Apply date</button></div>
        </div>
        <div id="predict-body"></div>
      </div>`;
    const body = document.getElementById("predict-body");
    const dateInput = document.getElementById("predict-date");
    const calendarInput = document.getElementById("predict-calendar");
    let initialA = route.query.get("a");
    let initialB = route.query.get("b");
    let initialVenue = (
      ["-1", "0", "1"].includes(route.query.get("venue"))
        ? route.query.get("venue")
        : "0"
    );
    let initialClass = (
      route.query.get("class") === "friendly"
        ? "friendly"
        : "competitive"
    );
    let initialMatchId = /^\d+$/.test(
      route.query.get("match") || "",
    )
      ? Number(route.query.get("match"))
      : null;

    const historicalPayload = async (
      dateValue,
      beforeDate = false,
    ) => {
      const year = Math.min(Number(dateValue.slice(0, 4)), Number(historyIndex.last.slice(0, 4)));
      const payload = await getJSON(`data/rankings-history/${year}.json`);
      const active = historicalRankingFromPayload(
        historyIndex,
        payload,
        dateValue,
        beforeDate,
      );
      let context = payload.opening_prediction_context;
      (payload.prediction_contexts || []).forEach((item) => {
        if (
          beforeDate
            ? item.date < dateValue
            : item.date <= dateValue
        ) {
          context = item;
        }
      });
      return { teams: active, context };
    };

    const loadDate = async (dateValue, preserveRequestedTeams = false) => {
      const currentA = document.getElementById("predict-a")?.value;
      const currentB = document.getElementById("predict-b")?.value;
      const currentVenue = document.getElementById(
        "predict-venue"
      )?.value;
      const currentClass = document.getElementById(
        "predict-class"
      )?.value;
      const preferredA = currentA || (
        preserveRequestedTeams ? initialA : null
      );
      const preferredB = currentB || (
        preserveRequestedTeams ? initialB : null
      );
      const preferredVenue = currentVenue || (
        preserveRequestedTeams ? initialVenue : "0"
      );
      const preferredClass = currentClass || (
        preserveRequestedTeams
          ? initialClass
          : "competitive"
      );
      selectedDate = dateValue;
      dateInput.value = validDate(dateValue);
      calendarInput.value = dateValue;
      document.getElementById("predict-date-error").textContent = "";
      dateInput.removeAttribute("aria-invalid");
      history.replaceState(null, "", cleanRouteURL("predict", "", new URLSearchParams({ date: dateValue })));
      body.innerHTML = `<div class="loading-shell" role="status"><span class="spinner" aria-hidden="true"></span><p>Loading ratings for ${escapeHTML(validDate(dateValue))}…</p></div>`;
      let linkedMatch = null;
      if (
        preserveRequestedTeams
        && initialMatchId !== null
      ) {
        const matchDecade = (
          Math.floor(Number(dateValue.slice(0, 4)) / 10)
          * 10
        );
        const matchPayload = await getJSON(
          `data/matches/${matchDecade}.json`,
        );
        linkedMatch = (matchPayload.matches || []).find(
          (match) => (
            Number(match.id) === initialMatchId
            && match.date === dateValue
          ),
        ) || null;
      }
      const preMatch = Boolean(linkedMatch);
      const useCurrent = (
        !preMatch
        && dateValue >= (
          summary.meta.rankings_as_of
          || summary.meta.results_through
        )
      );
      const historical = useCurrent
        ? null
        : await historicalPayload(dateValue, preMatch);
      const teams = useCurrent
        ? currentRankingForDate(currentState, dateValue)
        : historical.teams;
      if (teams.length < 2) {
        body.innerHTML = `<div class="empty"><h2>Not enough eligible teams</h2><p>Two teams must have reached 30 matches by this date.</p></div>`;
        return;
      }
      const codes = new Set(teams.map((team) => team.code));
      const codeA = codes.has(preferredA) ? preferredA : teams[0].code;
      const codeB = codes.has(preferredB) && preferredB !== codeA ? preferredB : teams.find((team) => team.code !== codeA).code;
      initialA = null;
      initialB = null;
      initialVenue = null;
      initialClass = null;
      initialMatchId = null;
      const options = (selected) => teams.map((team) => `<option value="${escapeHTML(team.code)}" ${team.code === selected ? "selected" : ""}>No. ${team.rank} · ${escapeHTML(team.nation)} · ${rating(team.rating)}</option>`).join("");
      body.innerHTML = `
        <div class="predictor">
          <div class="team-picker"><p class="eyebrow">Team one</p><select id="predict-a" aria-label="Team one">${options(codeA)}</select></div>
          <div class="versus" aria-hidden="true">v</div>
          <div class="team-picker"><p class="eyebrow">Team two</p><select id="predict-b" aria-label="Team two">${options(codeB)}</select></div>
        </div>
        <div class="toolbar section predict-options">
          <div class="field"><label for="predict-venue">Venue</label><select id="predict-venue"><option value="0">Neutral</option><option value="1">Team one at home</option><option value="-1">Team two at home</option></select></div>
          <div class="field"><label for="predict-class">Match class</label><select id="predict-class"><option value="competitive">Competitive</option><option value="friendly">Friendly</option></select></div>
        </div>
        ${!useCurrent && !preMatch ? `<div class="record-note"><strong>Historical forecast</strong><div><b>The selected-date ratings and latent means are exact global snapshots.</b> An arbitrary historical pairing is still an approximation because the static archive does not retain every old pairwise covariance. Open a completed match from Matches to see its exact stored pre-match W/D/L forecast.</div></div>` : ""}
        <div id="forecast"></div>
        <details class="section analysis-disclosure">
          <summary><span><span class="eyebrow">Reconciled score probabilities</span><b>Exact-score grid</b><small>Open the 6×6 table for scorelines from 0–0 to 5–5.</small></span></summary>
          <div class="analysis-disclosure-body"><div id="score-grid"></div></div>
        </details>
        <details class="section analysis-disclosure">
          <summary><span><span class="eyebrow">Projected post-match ratings</span><b>Effect of each winning margin</b><small>Open the table for draws and margins from five goals either way.</small></span></summary>
          <div class="analysis-disclosure-body"><div class="record-note"><strong>Isolated scenario</strong><div>The table applies this one hypothetical result using the scoring environment on the selected date. It holds the elite reference, opponent breadth and every other same-date result fixed. Historical rows also omit archived pairwise covariance. These are useful isolated effects, not a promise of the exact rating published after a real jointly updated matchday.</div></div><div id="margin-grid"></div></div>
        </details>`;

      const venueSelect = document.getElementById(
      "predict-venue"
    );
    const classSelect = document.getElementById(
      "predict-class"
    );
    venueSelect.value = ["-1", "0", "1"].includes(
      preferredVenue
    )
      ? preferredVenue
      : "0";
    classSelect.value = preferredClass === "friendly"
      ? "friendly"
      : "competitive";

      const byCode = new Map(teams.map((team) => [team.code, team]));
      const currentIndex = new Map(currentState.codes.map((code, index) => [code, index]));
      const n = currentState.codes.length;
      const cov = (i, j) => currentState.covariance[i * n + j];
      const logistic = (value) => 1 / (1 + Math.pow(10, -value / 400));
      const dayNumber = (() => { const [y, m, d] = dateValue.split("-").map(Number); return y * 400 + m * 32 + d; })();

      const update = () => {
        const first = byCode.get(document.getElementById("predict-a").value);
        const second = byCode.get(document.getElementById("predict-b").value);
        if (first.code === second.code) {
          document.getElementById("forecast").innerHTML = `<div class="error-panel"><h2>Choose two different teams</h2></div>`;
          document.getElementById("score-grid").innerHTML = "";
          document.getElementById("margin-grid").innerHTML = "";
          return;
        }
        const home = Number(document.getElementById("predict-venue").value);
        const friendly = document.getElementById("predict-class").value === "friendly";
        const year = Number(dateValue.slice(0, 4));
        const scale = useCurrent ? currentState.scale : historicalScale(year);
        const homePoints = useCurrent ? currentState.home : historicalHome(year);
        const drawBase = useCurrent ? currentState.draw : historicalDraw(year);
        const vi = first.se * first.se;
        const vj = second.se * second.se;
        const i = currentIndex.get(first.code);
        const j = currentIndex.get(second.code);
        let variance;
        let cross = 0;
        if (useCurrent) {
          cross = cov(i, j);
          variance = Math.max(0, vi + vj - 2 * cross);
        } else {
          variance = Math.max(0, vi + vj);
        }
        const firstVenue = useCurrent
          ? venueProfileFromState(currentState, i, dayNumber)
          : projectVenueProfile(first.venue_effect, dayNumber);
        const secondVenue = useCurrent
          ? venueProfileFromState(currentState, j, dayNumber)
          : projectVenueProfile(second.venue_effect, dayNumber);
        const venueParameters = summary.parameters.venue_effects;
        let globalVenue = homePoints * home;
        let countryVenue = home === 0 ? 0 : home * (
          Number(venueParameters.home_share)
            * Number(firstVenue?.dependence || 0)
          + Number(venueParameters.away_share)
            * Number(secondVenue?.dependence || 0)
        );
        if (
          linkedMatch
          && linkedMatch.date === dateValue
          && linkedMatch.a === first.code
          && linkedMatch.b === second.code
          && Number(linkedMatch.home) === home
        ) {
          globalVenue = Number(
            linkedMatch.global_home ?? globalVenue,
          );
          countryVenue = Number(
            linkedMatch.country_home ?? countryVenue,
          );
        }
        const difference = (
          scale * (first.latent - second.latent)
          + globalVenue
          + countryVenue
        );
        const expected = logistic(difference);
        const network = [0, 0, 0];
        currentState.nodes.forEach((node, index) => {
          const sampled = difference + Math.sqrt(2 * variance) * scale * node;
          const expectation = logistic(sampled);
          const draw = drawBase * 4 * expectation * (1 - expectation);
          [expectation - draw / 2, draw, 1 - expectation - draw / 2].forEach((value, outcome) => {
            network[outcome] += currentState.weights[index] * value;
          });
        });
        const baseTemperature = friendly ? currentState.friendly_temperature : currentState.competitive_temperature;
        let powered = network.map((value) => Math.pow(Math.max(1e-15, value), baseTemperature));
        let total = powered.reduce((sum, value) => sum + value, 0);
        const base = powered.map((value) => value / total);

        let layer = useCurrent ? currentState.forecast_layer : historical.context?.context;
        let firstScore;
        let secondScore;
        if (useCurrent) {
          firstScore = { release: layer.release, attack: layer.attack[i], defence: layer.defence[i], last_day: layer.last_day[i] };
          secondScore = { release: layer.release, attack: layer.attack[j], defence: layer.defence[j], last_day: layer.last_day[j] };
        } else {
          firstScore = first.score_state;
          secondScore = second.score_state;
        }
        const activeScore = layer?.release && layer.parameters && layer.calibration
          && firstScore?.release === layer.release && secondScore?.release === layer.release;
        const clipped = Math.min(1 - 1e-8, Math.max(1e-8, expected));
        const gapScale = layer?.parameters?.gap_scale ?? 1;
        const decay = layer?.parameters?.annual_decay ?? 0;
        const decayed = (state, field) => {
          if (!state) return 0;
          const elapsed = state.last_day < 0 ? 0 : Math.max(0, (dayNumber - state.last_day) / 400);
          return state[field] * Math.exp(-decay * elapsed);
        };
        const gap = 0.5 * gapScale * Math.log(clipped / (1 - clipped));
        const baseGoal = layer?.base_goal ?? 1.1;
        const lambdaA = Math.min(8, Math.max(0.05, Math.exp(Math.log(baseGoal) + gap + (activeScore ? decayed(firstScore, "attack") - decayed(secondScore, "defence") : 0))));
        const lambdaB = Math.min(8, Math.max(0.05, Math.exp(Math.log(baseGoal) - gap + (activeScore ? decayed(secondScore, "attack") - decayed(firstScore, "defence") : 0))));
        let probabilities = base;
        if (activeScore) {
          const score = poissonWDL(lambdaA, lambdaB);
          score[1] *= Math.exp(layer.calibration.draw_log_tilt);
          total = score.reduce((sum, value) => sum + value, 0);
          const temperature = friendly ? layer.calibration.friendly_temperature : layer.calibration.competitive_temperature;
          powered = score.map((value) => Math.pow(Math.max(1e-15, value / total), temperature));
          total = powered.reduce((sum, value) => sum + value, 0);
          const calibrated = powered.map((value) => value / total);
          const pooled = base.map((value, index) => layer.calibration.nfelo_weight * value + layer.calibration.score_weight * calibrated[index]);
          probabilities = boundaryPool(base, pooled);
        }
        const linkedSelection = Boolean(
          linkedMatch
          && linkedMatch.date === dateValue
          && linkedMatch.a === first.code
          && linkedMatch.b === second.code
          && Number(linkedMatch.home) === home
          && Boolean(linkedMatch.friendly) === friendly
        );
        if (linkedSelection) {
          probabilities = linkedMatch.p.map(Number);
        }
        const labels = [`${first.nation} win`, "Draw", `${second.nation} win`];
        const maximum = Math.max(...probabilities);
        document.getElementById("forecast").innerHTML = `<section class="forecast" aria-live="polite"><div class="forecast-title"><div><p class="eyebrow">Match forecast · ${validDate(dateValue)}</p><h2>${escapeHTML(first.nation)} v ${escapeHTML(second.nation)}</h2></div><span>${friendly ? "friendly" : "competitive"} · ${home === 0 ? "neutral" : home === 1 ? `${escapeHTML(first.nation)} home` : `${escapeHTML(second.nation)} home`}</span></div><div class="forecast-bars">${probabilities.map((value, index) => `<div class="forecast-outcome ${value === maximum ? "is-top" : ""}"><span>${escapeHTML(labels[index])}</span><strong>${percent(value)}</strong></div>`).join("")}</div><div class="forecast-meta"><span>${escapeHTML(first.nation)} <b>No. ${first.rank} · ${rating(first.rating)}</b></span><span>${escapeHTML(second.nation)} <b>No. ${second.rank} · ${rating(second.rating)}</b></span><span>Expected goals <b>${number(lambdaA, 2)}–${number(lambdaB, 2)}</b></span><span>Team-one venue adjustment <b>${signedRating(globalVenue + countryVenue)}</b>${home === 0 ? " · neutral" : ` · era ${signedRating(globalVenue)}, countries ${signedRating(countryVenue)}`}</span></div></section>`;

        const massesA = poissonMasses(lambdaA, 40);
        const massesB = poissonMasses(lambdaB, 40);
        const rawOutcomes = [0, 0, 0];
        massesA.forEach((massA, goalsA) => {
          massesB.forEach((massB, goalsB) => {
            const outcome = goalsA > goalsB ? 0 : goalsA === goalsB ? 1 : 2;
            rawOutcomes[outcome] += massA * massB;
          });
        });
        const outcomeFactor = probabilities.map((value, index) => value / rawOutcomes[index]);
        const rakedCell = (goalsA, goalsB) => {
          const outcome = goalsA > goalsB ? 0 : goalsA === goalsB ? 1 : 2;
          return massesA[goalsA] * massesB[goalsB] * outcomeFactor[outcome];
        };
        const displayedMass = [0,1,2,3,4,5].reduce((outer, goalsA) => (
          outer + [0,1,2,3,4,5].reduce((inner, goalsB) => inner + rakedCell(goalsA, goalsB), 0)
        ), 0);
        document.getElementById("score-grid").innerHTML = `<div class="table-hint" aria-hidden="true">Swipe to see every scoreline →</div><div class="table-shell score-grid"><table><thead><tr><th>${escapeHTML(first.nation)} ↓ · ${escapeHTML(second.nation)} →</th>${[0,1,2,3,4,5].map((goal) => `<th class="numeric">${goal}</th>`).join("")}</tr></thead><tbody>${[0,1,2,3,4,5].map((goalsA) => `<tr><th class="numeric">${goalsA}</th>${[0,1,2,3,4,5].map((goalsB) => `<td class="numeric ${goalsA > goalsB ? "score-win" : goalsA < goalsB ? "score-loss" : "score-draw"}">${percent(rakedCell(goalsA, goalsB))}</td>`).join("")}</tr>`).join("")}</tbody></table></div><p class="muted small">The scoreline probabilities are reconciled to the final W/D/L forecast. The 36 cells show 0–0 through 5–5; the remaining ${percent(Math.max(0, 1 - displayedMass))} covers scorelines involving six or more goals.</p>`;

        const environment = useCurrent
          ? currentState.margin_environment ?? 1.1
          : historical.context?.margin_environment
            ?? currentState.margin_environment
            ?? 1.1;
        const beta = Math.log(10) * scale / 400;
        const quality = summary.parameters.network.quality_scale;
        const classRatio = friendly ? summary.parameters.network.friendly_information_ratio : 1;
        const rows = [];
        for (let margin = -5; margin <= 5; margin += 1) {
          const result = margin > 0 ? 1 : margin < 0 ? 0 : 0.5;
          const weight = quality * marginWeight(margin, environment) * classRatio;
          const information = Math.max(1e-8, expected * (1 - expected));
          const curvature = weight * beta * beta * information;
          const denominator = 1 + curvature * variance;
          const directionA = vi - cross;
          const directionB = cross - vj;
          const scalar = weight * beta * (result - expected) / denominator;
          const deltaA = directionA * scalar;
          const deltaB = directionB * scalar;
          const postVarA = Math.max(0, vi - directionA * directionA * curvature / denominator);
          const postVarB = Math.max(0, vj - directionB * directionB * curvature / denominator);
          const postA = first.mean + first.reliability * deltaA - confidenceZ * Math.sqrt(postVarA);
          const postB = second.mean + second.reliability * deltaB - confidenceZ * Math.sqrt(postVarB);
          rows.push({ margin, postA, postB, changeA: postA - first.rating, changeB: postB - second.rating });
        }
        document.getElementById("margin-grid").innerHTML = `<div class="table-hint" aria-hidden="true">Swipe to see both teams →</div><div class="table-shell margin-grid"><table><thead><tr><th>Result</th><th class="numeric">${escapeHTML(first.nation)} rating</th><th class="numeric">Change</th><th class="numeric">${escapeHTML(second.nation)} rating</th><th class="numeric">Change</th></tr></thead><tbody>${rows.map((row) => `<tr><td>${row.margin > 0 ? `${escapeHTML(first.nation)} by ${row.margin}` : row.margin < 0 ? `${escapeHTML(second.nation)} by ${Math.abs(row.margin)}` : "Draw"}</td><td class="numeric"><b>${rating(row.postA)}</b></td><td class="numeric ${row.changeA >= 0 ? "positive" : "negative"}">${row.changeA >= 0 ? "+" : ""}${rating(row.changeA)}</td><td class="numeric"><b>${rating(row.postB)}</b></td><td class="numeric ${row.changeB >= 0 ? "positive" : "negative"}">${row.changeB >= 0 ? "+" : ""}${rating(row.changeB)}</td></tr>`).join("")}</tbody></table></div>`;
        history.replaceState(
        null,
        "",
        cleanRouteURL(
          "predict",
          "",
          new URLSearchParams({
            date: dateValue,
            a: first.code,
            b: second.code,
            venue: String(home),
            "class": (
              friendly ? "friendly" : "competitive"
            ),
            ...(linkedSelection
              ? { match: String(linkedMatch.id) }
              : {}),
          }),
        ),
      );
      };
      ["predict-a", "predict-b", "predict-venue", "predict-class"].forEach((id) => document.getElementById(id).addEventListener("change", update));
      update();
    };

    const applyDate = () => {
      const chosen = inputDate(dateInput.value);
      const error = historyDateInputError(dateInput.value, historyIndex.first, maximumPredictionDate);
      if (!chosen || error) {
        document.getElementById("predict-date-error").textContent = error || "Enter a complete date as DD/MM/YYYY.";
        dateInput.setAttribute("aria-invalid", "true");
        return;
      }
      loadDate(chosen, false);
    };
    dateInput.addEventListener("input", () => {
      dateInput.value = formatHistoryDateInput(dateInput.value);
      const error = historyDateInputError(dateInput.value, historyIndex.first, maximumPredictionDate);
      document.getElementById("predict-date-error").textContent = error;
      if (error) dateInput.setAttribute("aria-invalid", "true"); else dateInput.removeAttribute("aria-invalid");
    });
    dateInput.addEventListener("keydown", (event) => { if (event.key === "Enter") applyDate(); });
    document.getElementById("predict-apply").addEventListener("click", applyDate);
    document.getElementById("predict-calendar-button").addEventListener("click", () => {
      if (typeof calendarInput.showPicker === "function") calendarInput.showPicker(); else calendarInput.click();
    });
    calendarInput.addEventListener("change", () => { if (calendarInput.value) loadDate(calendarInput.value, false); });
    await loadDate(selectedDate, true);
  }

  function ratingChart(history, nation) {
    if (!history || history.length < 2) return `<div class="empty">A rating line begins after 30 matches.</div>`;
    const last = history[history.length - 1];
    const peak = history.reduce((best, point) => point.rating > best.rating ? point : best, history[0]);
    return interactiveRatingChart([
      { label: nation, history },
    ], {
      ariaLabel: `${nation} rating history`,
      summary: `<div class="chart-summary"><span>First eligible: ${validDate(history[0].date)} · ${rating(history[0].rating)}</span><span>Peak: ${validDate(peak.date)} · ${rating(peak.rating)}</span><span>Latest appearance: ${validDate(last.date)} · ${rating(last.rating)}</span></div>`,
    });
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

const displayName = cutoff && latestPoint?.historical_name
  ? latestPoint.historical_name
  : team.nation;
const lineageNames = completePublicLineageNames([
  team.nation,
  ...(team.lineage_names || []),
]);
const lineageNote = lineageNames.length > 1
  ? (
    '<div class="record-note team-lineage-note">'
    + "<strong>Lineage</strong><div><b>"
    + escapeHTML(formatPublicNameList(lineageNames))
    + "</b> share one continuous rating history. "
    + "Match names follow the date played.</div></div>"
  )
  : "";
    const historicalStats = availableMatches.reduce((stats, match) => {
      stats.matches += 1;
      stats.gf += match.gf;
      stats.ga += match.ga;
      stats[match.result] += 1;
      return stats;
    }, { matches: 0, gf: 0, ga: 0, W: 0, D: 0, L: 0 });
    const historicalPeak = history.length ? history.reduce((best, point) => point.rating > best.rating ? point : best, history[0]) : null;
    const venueAsOfDate = (
      cutoff
      || team.rating_date
      || summary.meta.rankings_as_of
    );
    const venueProfile = projectVenueProfile(
      cutoff
        ? latestPoint?.venue_effect
        : team.venue_effect,
      modelDayNumber(venueAsOfDate),
    );
    const scoreProfile = projectScoreProfile(
      latestPoint?.score_state,
      modelDayNumber(venueAsOfDate),
    );
    const venueInterval = venueProfile
      ? [
        venueProfile.dependence - 1.96 * venueProfile.se,
        venueProfile.dependence + 1.96 * venueProfile.se,
      ]
      : null;
    const venueEvidence = venueProfile
      ? (
        venueProfile.reliability >= 0.6
          ? "Strong"
          : venueProfile.reliability >= 0.3
            ? "Moderate"
            : "Limited"
      )
      : "";
    const venueTendency = venueProfile
      ? (
        venueProfile.hosting_adjustment >= 7
          ? `${displayName} has tended to benefit more from home conditions than the average team.`
          : venueProfile.hosting_adjustment <= -7
            ? `${displayName} has tended to depend less on home conditions than the average team.`
            : `${displayName} is currently close to the average home-and-away pattern.`
      )
      : "";
    const venuePanel = venueProfile ? `
      <section class="venue-profile" aria-labelledby="venue-profile-title">
        <div class="venue-profile-copy">
          <p class="eyebrow">Match adjustment${cutoff ? ` · ${validDate(venueAsOfDate)}` : ""}</p>
          <h2 id="venue-profile-title">Home and away</h2>
          <p><b>${escapeHTML(venueTendency)}</b> Forecast-only adjustment on top of the worldwide home advantage.</p>
        </div>
        <div class="venue-profile-highlights" aria-label="Home and away summary">
          <div class="venue-highlight"><span>Extra at home</span><strong>${signedRating(venueProfile.hosting_adjustment)}</strong></div>
          <div class="venue-highlight"><span>Extra when away</span><strong>${signedRating(venueProfile.away_adjustment)}</strong></div>
          <div class="venue-highlight"><span>Evidence</span><strong>${venueEvidence}</strong></div>
        </div>
        <details class="venue-profile-details">
          <summary>See uncertainty and technical details</summary>
          <div class="venue-detail-grid">
            <div><span>Full dependence estimate</span><strong>${signedRating(venueProfile.dependence)}</strong></div>
            <div><span>95% range</span><strong>${signedRating(venueInterval[0])} to ${signedRating(venueInterval[1])}</strong></div>
            <div><span>Standard error</span><strong>±${rating(venueProfile.se)}</strong></div>
            <div><span>Non-neutral appearances</span><strong>${number(venueProfile.matches)}</strong></div>
            <div><span>Reliability</span><strong>${percent(venueProfile.reliability)}</strong></div>
            <div><span>Extra at neutral venue</span><strong>${signedRating(venueProfile.neutral)}</strong></div>
          </div>
          <p>The profile changes after every non-neutral matchday this team plays. All forecasts on that date use the old values first, then the day’s evidence is learned together. Between appearances, the estimate gradually moves towards the worldwide average. Neutral matches do not update it. <a href="#/methodology?section=venue">How this is calculated →</a></p>
        </details>
      </section>` : "";
    const scorePanel = scoreProfile ? `
      <section class="venue-profile score-profile" aria-labelledby="score-profile-title">
        <div class="venue-profile-copy score-profile-copy">
          <p class="eyebrow">Forecast-only scoring tendencies</p>
          <h2 id="score-profile-title">Attack and defence</h2>
          <p>Recent scoring above or below what strength, opposition and venue already predicted.</p>
        </div>
        <div class="venue-profile-highlights score-profile-highlights" aria-label="Attack and defence summary">
          <div class="venue-highlight"><span>Own expected goals</span><strong>${signedPercent(scoreProfile.attack_goal_change)}</strong></div>
          <div class="venue-highlight"><span>Opponent expected goals</span><strong>${signedPercent(scoreProfile.opponent_goal_change)}</strong></div>
        </div>
        <details class="venue-profile-details score-profile-details">
          <summary>See technical details</summary>
          <div class="venue-detail-grid">
            <div><span>Attack residual</span><strong>${number(scoreProfile.attack, 4)}</strong></div>
            <div><span>Defence residual</span><strong>${number(scoreProfile.defence, 4)}</strong></div>
          </div>
          <p>The tendencies update after each completed matchday and gradually move towards neutral during inactivity. They refine forecast probabilities only, never the public rating or ranking. <a href="#/methodology?section=forecast">How the forecast layer works →</a></p>
        </details>
      </section>` : "";
    setTitle(displayName);
    content.innerHTML = `
      <div class="page">
        <section class="team-hero">
          <div><p class="eyebrow">${cutoff ? `Historical record through ${validDate(cutoff)}` : team.rank ? `Current world no. ${team.rank}` : "Historical team record"}</p><h1>${escapeHTML(displayName)}</h1>${cutoff && displayName !== team.nation ? `<p class="muted">Part of the continuous ${escapeHTML(team.nation)} rating history</p>` : ""}</div>
          <div class="team-rating"><strong>${rating(cutoff ? latestPoint?.rating : team.rating)}</strong><span>${cutoff && latestPoint ? `after ${validDate(latestPoint.date)} · ` : ""}uncertainty ${rating(cutoff ? latestPoint?.se : team.se)}</span></div>
        </section>
        ${lineageNote}
        <div class="team-stats">
          <div><span>Matches</span><strong>${number(cutoff ? historicalStats.matches : team.matches)}</strong></div><div><span>Record</span><strong>${cutoff ? `${historicalStats.W}–${historicalStats.D}–${historicalStats.L}` : `${team.wins}–${team.draws}–${team.losses}`}</strong></div><div><span>Goals</span><strong>${cutoff ? `${historicalStats.gf}–${historicalStats.ga}` : `${team.gf}–${team.ga}`}</strong></div><div><span title="Effective variety of recent opponents; higher values mean broader evidence.">${cutoff ? "Latest match" : "Opponent breadth"}</span><strong>${cutoff ? (availableMatches.length ? validDate(availableMatches[0].date) : "—") : number(team.breadth, 1)}</strong></div><div><span>${cutoff ? "Peak by date" : "All-time peak"}</span><strong>${rating(cutoff ? historicalPeak?.rating : team.peak?.rating)}</strong></div>
        </div>
        ${venuePanel}
        ${scorePanel}
        <nav class="context-actions team-context-actions" aria-label="Team tools"><a class="button button-quiet" href="#/compare?a=${encodeURIComponent(team.code)}">Compare this team</a><a class="button button-quiet" href="#/predict?a=${encodeURIComponent(team.code)}${cutoff ? `&date=${encodeURIComponent(cutoff)}` : ""}">Predict a matchup</a><a class="button button-quiet" href="#/rankings">Current rankings</a></nav><section class="section"><div class="section-heading"><div><p class="eyebrow">Rating after each match</p><h2>Rating history${cutoff ? ` to ${validDate(cutoff)}` : ""}</h2></div></div>${ratingChart(history, displayName)}</section>
        <section class="section"><div class="section-heading"><div><p class="eyebrow">${cutoff ? "Matches through selected date" : "Complete match history"}</p><h2>Matches</h2></div><a class="button button-quiet" href="#/matches?team=${encodeURIComponent(team.code)}">Open in explorer →</a></div><div id="team-matches"></div><div class="pagination"><span id="team-count" class="muted small" aria-live="polite"></span><div class="pagination-actions"><button id="team-more" class="button">Show more</button><button id="team-all" class="button button-quiet">Show all</button></div></div></section>
      </div>`;
    initialiseRatingHistoryCharts(content);
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


function buildFAQItems() {
  return [
    {
      question: "What is NFELO?",
      answer: "NFELO is an independent rating and forecasting system for men’s international football. It uses results, opponents and shared opponents to connect national teams across countries, regions and eras. The same model powers the current rankings, historical tables, team records and match predictions throughout the site."
    },
    {
      question: "How is NFELO different from the World Football Elo Ratings?",
      answer: "Both are Elo-style systems, but NFELO keeps track of uncertainty and the wider opponent network rather than updating only the two teams in isolation. It is more cautious when a team has faced a narrow group of opponents, and it does not give World Cup matches an automatic extra multiplier. One public rating is used for rankings, while separate attack and defence tendencies refine match probabilities in an expandable team-page section."
    },
    {
      question: "What does a team’s rating mean?",
      answer: "It is NFELO’s cautious estimate of that team’s strength on the selected date. A team with limited or weakly connected evidence is held back more than one supported by a broad range of opponents. The gap between two ratings is more informative than treating either number as an absolute measure of quality."
    },
    {
      question: "How are the rankings calculated?",
      answer: "Results move the estimates of teams throughout the connected opponent network, so a result can also affect teams linked through shared opponents. NFELO then allows for how broad and how certain each team’s evidence is before publishing one rating. That same rating is used on every ranking, history and record page."
    },
    {
      question: "What is the network element?",
      answer: "Not every national team plays every other one, and some regions are much more connected than others. Shared opponents let NFELO compare teams across those gaps and reduce the apparent advantage of repeatedly playing within a small, closed group. This is especially important for historical and lightly scheduled teams."
    },
    {
      question: "Does NFELO use different K-factors for friendlies, qualifiers and tournaments?",
      answer: "NFELO does not use a traditional K-factor. Confirmed friendlies contribute about 78.6% as much rating information as competitive matches; qualifiers and tournaments use the full weight. Testing different friendly weights by era did not improve later forecasts, so one friendly weight is retained."
    },
    {
      question: "Why is a friendly’s rating change not always 78.6% of a competitive match?",
      answer: "The 78.6% applies to the information learned, not directly to the displayed points. The opponent, result, winning margin, uncertainty and other matches on the same date all affect the eventual rating movement. It is therefore a model weight, not a promise that two superficially similar matches will produce changes in a fixed ratio."
    },
    {
      question: "How is home advantage handled?",
      answer: "A home forecast combines the worldwide home advantage for that era with cautious, changing estimates for the two countries involved. Team pages show how much those country profiles add when the team is home or away, along with a simple evidence label. These adjustments affect forecasts only; neutral matches receive neither and do not update them."
    },
    {
      question: "Why are a team’s home and away adjustments linked?",
      answer: "The historical data record the host first almost all the time, so they cannot reliably separate a country’s extra benefit at home from its extra difficulty away. NFELO therefore uses one shared estimate, displayed as equal and opposite home and away adjustments. That simpler version also forecast later results better than separate national home and away values."
    },
    {
      question: "What happens at a neutral venue?",
      answer: "Neither the worldwide home advantage nor a country-specific adjustment is used at a neutral venue. The match still updates team strength and scoring tendencies in the normal way, but it does not teach the country home-and-away profile. Separate national neutral-venue effects were tested and did not improve later forecasts."
    },
    {
      question: "When does a team’s home-and-away estimate change?",
      answer: "It is updated after every non-neutral matchday the team plays. All matches on that date are predicted first, then the day’s evidence is learned together. Between appearances, the estimate gradually fades towards the worldwide average. Team pages label its evidence as limited, moderate or strong."
    },
    {
      question: "How does goal margin affect ratings?",
      answer: "A larger win usually provides more information than a one-goal win, but each additional goal matters less than the previous one. This prevents a single extreme score from overwhelming the wider evidence. The calculation also allows for the fact that typical scorelines have changed over football history."
    },
    {
      question: "How are new teams given a starting rating?",
      answer: "A new team starts relative to the established international pool active around its debut, not at one universal number. The size of that active pool also matters, which avoids giving early entrants an automatic advantage. Initial estimates are deliberately uncertain and can adapt quickly as results accumulate."
    },
    {
      question: "How are match probabilities calculated?",
      answer: "NFELO starts with underlying strength, uncertainty, era and venue. A forecast-only layer then uses each team’s recent attacking and defensive tendencies to refine the win, draw and loss percentages without changing the public ranking. Team pages show these tendencies in an expandable section."
    },
    {
      question: "Why can a lower-rated team be the forecast favourite?",
      answer: "The public rating is deliberately cautious when evidence is narrow or uncertain. A match forecast uses the fuller strength estimate, venue and scoring tendencies for that particular matchup. A lower-rated team can therefore be a slight favourite in one match without either the ranking or forecast being an error."
    },
    {
      question: "Why keep the forecasting layer separate from the rankings?",
      answer: "One rating keeps the ranking clear and comparable. Attack and defence tendencies are useful for predicting one match, but compressing them into the same number would make the ranking less meaningful. They are displayed separately on team pages."
    },
    {
      question: "Can the scoring layer reverse NFELO’s most likely result?",
      answer: "No. It can improve how the probability is divided among the three outcomes, but it stops before changing whether the underlying network model favours a win, draw or loss. This preserves one stable match pick while still using team-specific scoring information."
    },
    {
      question: "What does a probability such as 45%–29%–26% mean?",
      answer: "It means a 45% chance that the first-listed team wins, a 29% chance of a draw and a 26% chance that the second team wins. The first team is the single most likely outcome, but a draw or loss is still more likely in total. Probabilities describe uncertainty; they are not a claim that the favourite should always win."
    },
    {
      question: "How is the methodology tested?",
      answer: `The current formula is replayed over ${number(summary.validation.retrospective.matches)} pre-match forecasts through ${validDate(summary.validation.retrospective.cutoff)}. It is judged both by how often its most likely win, draw or loss is correct and, in technical comparisons, by log loss, which scores all three probabilities. Historical benchmark tests use earlier periods to choose a model and later periods to score it, making comparison with simpler Elo methods and published WFER forecasts more meaningful. Future fixtures are also stored before their results are known.`
    },
    {
      question: "How accurate is the current NFELO formula?",
      answer: `Across ${number(summary.validation.retrospective.matches)} historical pre-match forecasts, the current formula’s most likely win, draw or loss was correct ${percent(summary.validation.retrospective.accuracy)} of the time. That may sound modest, but international football has many close matchups and three possible outcomes. It is a full-history replay of the final formula, not a promise about any single match.`
    },
    {
      question: "What does better log loss mean in practice?",
      answer: "Log loss judges all three probabilities rather than only asking whether the top choice was correct. Lower is better: it rewards useful confidence and penalises a model that is too certain about an outcome that does not happen. For example, a confidently wrong forecast is treated as worse than a cautious one in an evenly matched game."
    },
    {
      question: "How are extra time and penalty shootouts treated?",
      answer: "A match that remains level after its recorded playing period counts as a draw for ratings and win/draw/loss forecasts. A shootout decides who advances, but it does not turn that draw into a normal match win. This keeps the model focused on football played rather than the separate shootout procedure."
    },
    {
      question: "Can I view rankings from a previous date?",
      answer: "Yes. The History page accepts a typed date or calendar selection and reconstructs the latest completed matchday on or before it. It also uses names appropriate to that time, such as West Germany, the Soviet Union and Czechoslovakia, and historical team links open at the same date."
    },
    {
      question: "How often is the site updated?",
      answer: "The site checks results and fixtures three times each day, timed around the main international match windows. It rebuilds the complete history only after the new data pass validation. If a source is incomplete or a check fails, the last verified site stays online unchanged."
    },
    {
      question: "Why can the two teams’ ratings move by different amounts?",
      answer: "NFELO is not a two-team, zero-sum table in which every point gained must be lost by the opponent. A result affects the wider opponent network, while the two teams can also have different levels of uncertainty and opponent coverage. Their published ratings can therefore move by different amounts."
    },
    {
      question: "Why can an inactive team remain highly ranked?",
      answer: "A period without matches does not prove that a team suddenly became weak, so its estimated strength is not simply erased. Instead, uncertainty grows and gradually lowers its cautious public rating. This deals with long gaps such as wartime inactivity or irregular schedules without rewriting historical ratings and peaks."
    },
    {
      question: "Can ratings from different eras be compared directly?",
      answer: "They can be compared on NFELO’s historical scale, with adjustments for era, schedule breadth and uncertainty. The network and cautious rating are designed to avoid automatically placing the earliest teams above everyone who followed. Cross-era values are still estimates, not proof of what two teams separated by a century would do in a real match."
    },
    {
      question: "Why does NFELO include territories and some teams outside FIFA?",
      answer: "The site follows the senior international histories available in its sources rather than FIFA membership alone. Territories and historical teams use the same match-count, activity and evidence rules as everyone else, and an inactive team may appear only in historical views. Inclusion is a data decision, not a statement about political status or competition eligibility."
    },
    {
      question: "How are several matches played on the same date handled?",
      answer: "Every match on a known date is predicted before any result from that date is learned. The results are then learned together, so source order cannot give one same-day match advance knowledge of another. The same rule is used for team strength, country venue profiles and attack and defence tendencies."
    },
    {
      question: "Why does NFELO publish only one ranking?",
      answer: "The fuller strength estimate is useful for forecasting but can flatter teams from small, isolated historical groups. The published rating adds caution for uncertainty and limited opponent breadth, producing one consistent ranking across the site. Attack and defence values remain supporting forecast information rather than becoming competing rankings."
    },
    {
      question: "Why might an older report show a different accuracy or log loss?",
      answer: `Older reports describe earlier versions or narrower tests. The current headline is ${percent(summary.validation.retrospective.accuracy)} top-result accuracy across ${number(summary.validation.retrospective.matches)} forecasts. Exact technical scoring is kept in the Methodology page, while archived research remains available for reproducibility.`
    },
    {
      question: "Why might a recent result or fixture be missing?",
      answer: "NFELO depends on external data feeds and publishes only data that pass its checks. A match can appear late when a source has not updated, a team name cannot be matched safely or sources disagree about details. The update fails closed in those cases, so uncertain data do not replace the last verified site."
    },
    {
      question: "What should I do if I find incorrect data?",
      answer: "If NFELO differs from a reliable published result, report the teams, date, score, competition and venue through the project’s GitHub repository. A link to the supporting source is particularly helpful, as it allows the correction to be checked without weakening the automated validation rules.",
      link: "https://github.com/nfelo/nfelo.github.io",
      linkLabel: "Open the NFELO GitHub repository →"
    }
  ];
}

function faqSearchTokens(value) {
  return value
    .normalize("NFKD")
    .replace(/\p{Diacritic}/gu, "")
    .toLocaleLowerCase()
    .match(/[\p{L}\p{N}]+/gu)?.map((token) => {
      if (token.length > 4 && token.endsWith("ies")) return `${token.slice(0, -3)}y`;
      if (token.length > 3 && token.endsWith("s")) return token.slice(0, -1);
      return token;
    }) || [];
}

function renderFAQ() {
  setTitle("Frequently asked questions");
  content.innerHTML = `
    <article class="page page-narrow prose faq-page">
      <p class="eyebrow">Understanding the site</p>
      <h1>Frequently asked questions</h1>
      <p class="lede">Straightforward answers about ratings, forecasts, historical data, tournaments, records and methodology.</p>
      <div class="faq-tools" role="search">
        <div class="field field-grow">
          <label for="faq-search">Search questions</label>
          <input id="faq-search" type="search" placeholder="Ratings, friendlies, penalties…" autocomplete="off">
        </div>
        <div class="faq-actions" aria-label="Question controls">
          <button class="button" type="button" id="faq-expand">Expand all</button>
          <button class="button button-quiet" type="button" id="faq-collapse">Collapse all</button>
        </div>
      </div>
      <p id="faq-count" class="muted small" aria-live="polite"></p>
      <div id="faq-list" class="faq-list"></div>
      <div class="callout faq-more"><b>Looking for the exact calculations?</b> Start with <a href="#/methodology?section=strength">how the strength model works</a>, or open the full Methodology page from the main navigation.</div>
    </article>`;

  const list = document.getElementById("faq-list");
  const count = document.getElementById("faq-count");
  const search = document.getElementById("faq-search");
  const faqItems = buildFAQItems();

  const draw = () => {
    const query = search.value.trim();
    const terms = faqSearchTokens(query);
    const filtered = faqItems.filter((item) => {
      const words = faqSearchTokens(`${item.question} ${item.answer}`);
      return terms.every((term) =>
  words.some((word) => word.includes(term))
);
    });
    list.innerHTML = filtered.length ? filtered.map((item, index) => `
      <details class="faq-item"${!query && index === 0 ? " open" : ""}>
        <summary>${escapeHTML(item.question)}</summary>
        <div class="faq-answer"><p>${escapeHTML(item.answer)}</p>${item.link ? `<a class="faq-source-link" href="${escapeHTML(item.link)}" rel="external">${escapeHTML(item.linkLabel)}</a>` : ""}</div>
      </details>`).join("") : `<div class="empty-state"><h2>No matching questions</h2><p>Try a broader term or clear the search.</p></div>`;
    count.textContent = query ? `${filtered.length} of ${faqItems.length} questions shown` : `${faqItems.length} questions`;
  };

  search.addEventListener("input", draw);
  document.getElementById("faq-expand").addEventListener("click", () => {
    list.querySelectorAll("details").forEach((item) => { item.open = true; });
  });
  document.getElementById("faq-collapse").addEventListener("click", () => {
    list.querySelectorAll("details").forEach((item) => { item.open = false; });
  });
  draw();
}

  function renderMethodology(query = new URLSearchParams()) {
    setTitle("Methodology");
    const p = summary.parameters;
    const f = p.forecast_layer;
    const v = p.venue_effects;
    const replay = summary.validation.retrospective;
    const benchmark = summary.validation.nested;
    content.innerHTML = `
      <article class="page page-narrow prose methodology-page">
        <p class="eyebrow">Model · evidence · limitations</p>
        <h1>Methodology</h1>
        <p class="lede">NFELO uses one connected model of team strength. It publishes a cautious rating for rankings and records, while match forecasts also use venue, uncertainty and team-specific scoring patterns.</p>

        <nav class="method-contents" aria-label="Methodology sections">
          <a href="#/methodology?section=overview">Plain-English overview</a>
          <a href="#/methodology?section=strength">Connected strength</a>
          <a href="#/methodology?section=venue">Home and away</a>
          <a href="#/methodology?section=forecast">Match forecasts</a>
          <a href="#/methodology?section=learning">Learning from results</a>
          <a href="#/methodology?section=ratings">Published ratings</a>
          <a href="#/methodology?section=validation">Evidence and accuracy</a>
          <a href="#/methodology?section=limits">Limits and reproducibility</a>
        </nav>

        <section class="method-section" aria-labelledby="method-overview">
          <h2 id="method-overview" tabindex="-1">In plain English</h2>
          <ol class="method-steps">
            <li><b>Connect the opposition.</b> A result informs not only the two teams, but also the network created by their shared opponents.</li>
            <li><b>Respect uncertainty.</b> New, inactive or narrowly connected teams are treated more cautiously than teams supported by broad recent evidence.</li>
            <li><b>Account for the venue.</b> A home match combines the worldwide advantage for that era with changing estimates for both countries. Neutral matches receive neither.</li>
            <li><b>Predict before learning.</b> Every match on a known date is forecast from the same start-of-day information, then all results on that date are learned together.</li>
            <li><b>Use the score carefully.</b> Surprise and winning margin affect how much is learned, with diminishing weight for additional goals and a smaller information weight for friendlies.</li>
            <li><b>Keep rankings simple.</b> One public rating is used everywhere. Separate attack and defence tendencies can refine match probabilities, but never change ratings or ranking order; team pages show them only when requested.</li>
          </ol>
        </section>

        <section class="method-section" aria-labelledby="method-strength">
          <h2 id="method-strength" tabindex="-1">Connected strength and uncertainty</h2>
          <p>Team strength is represented by a joint estimate <code>r ~ N(μ,Σ)</code>. The mean <code>μ</code> contains each team’s estimated strength; the covariance matrix <code>Σ</code> preserves links created by common opponents. This is why evidence can move a connected team even when it did not play that day.</p>
          <p>Uncertainty grows slowly when a team is not playing, using:</p>
          <div class="formula">Σᵢᵢ ← Σᵢᵢ + ${number(p.network.drift_sd, 10)}² Δt</div>
          <p>The underlying strength does not simply collapse during inactivity. Instead, the public rating becomes more cautious as uncertainty grows.</p>
          <details class="method-details">
            <summary>Starting strength for a new team</summary>
            <p>A debutant begins relative to the established teams active around that date, with standard deviation <b>${rating(p.network.prior_sd)}</b>:</p>
            <div class="formula">μnew = median(active pool) ${p.debut.offset < 0 ? "−" : "+"} ${number(Math.abs(p.debut.offset), 10)} ${p.debut.pool_slope < 0 ? "−" : "+"} ${number(Math.abs(p.debut.pool_slope), 10)} ln[(A+10)/50]</div>
            <p><code>A</code> is the active international pool. Teams debuting on the same complete date receive the same pre-match pool estimate.</p>
          </details>
        </section>

        <section class="method-section" aria-labelledby="method-venue">
          <h2 id="method-venue" tabindex="-1">Home, away and neutral venues</h2>
          <p>Home advantage has two parts: a worldwide baseline that changes through football history, and a cautious country profile that can also change over time.</p>
          <div class="formula">C₁₂ = h(d₁+d₂)/2<br>δ = a(y)(μ₁−μ₂) + H(y)h + C₁₂<br>E = 1 / [1 + 10^(−δ/400)]</div>
          <p><code>h</code> is +1 when team one is at home, −1 when team two is at home and 0 at a neutral venue. <code>H(y)</code> is the worldwide home advantage for year <code>y</code>; <code>d₁</code> and <code>d₂</code> are the two countries’ profiles. Each profile contributes half when hosting and the opposite half when away. Both venue terms are exactly zero at a neutral ground.</p>
          <p>Home and away are shown as two views of one estimate because the match record does not reliably identify separate national home and away effects. The shared version performed better on later results. The profile is updated after every non-neutral matchday the country plays: every forecast on that date uses the same old profile, then all of that day’s venue evidence is learned together. Neutral matches do not update it. Sparse or old evidence stays close to the worldwide average and moves halfway back towards it every <b>${number(v.half_life_years, 0)} years</b>.</p>
          <div class="table-hint" aria-hidden="true">Swipe horizontally to see every column →</div>
          <div class="table-shell parameter-table"><table><thead><tr><th>Year</th><th class="numeric">Gap scale</th><th class="numeric">Equivalent divisor</th><th class="numeric">Worldwide home advantage</th><th class="numeric">Equal-team draw rate</th></tr></thead><tbody>${p.knot_years.map((year, index) => `<tr><td>${year}${index === p.knot_years.length - 1 ? "+" : ""}</td><td class="numeric">${number(p.calibration_scale[index], 4)}</td><td class="numeric">${number(400 / p.calibration_scale[index], 1)}</td><td class="numeric">${rating(p.home_advantage[index])}</td><td class="numeric">${percent(p.draw_probability[index])}</td></tr>`).join("")}</tbody></table></div>
          <details class="method-details">
            <summary>Exact country-profile update</summary>
            <p>Each country starts at zero with a ${rating(v.prior_sd)}-point standard deviation. Between matchdays:</p>
            <div class="formula">r = 2^(−Δt/${number(v.half_life_years)})<br>dᵢ(t) = r dᵢ(t₀)<br>Vᵢ(t) = ${rating(v.prior_sd)}² − [${rating(v.prior_sd)}²−Vᵢ(t₀)]r²</div>
            <p>For a non-neutral result, <code>zᵢ=h/2</code>, <code>b=ln(10)/400</code> and <code>q</code> is ${number(v.friendly_learning_ratio, 5)} for a friendly or 1 for a competitive match:</p>
            <div class="formula">gᵢ = qbzᵢ(S−E)<br>cᵢ = qb²zᵢ²E(1−E)<br>Vᵢ′ = 1 / (1/Vᵢ + Σcᵢ)<br>dᵢ′ = dᵢ + Vᵢ′Σgᵢ</div>
            <p>Neutral matches do not update this profile. Its remaining uncertainty is reported on team pages but is not added to match variance because that made later forecasts worse.</p>
          </details>
        </section>

        <section class="method-section" aria-labelledby="method-forecast">
          <h2 id="method-forecast" tabindex="-1">From strength to match probabilities</h2>
          <p>The expected fractional score <code>E</code> is converted into win, draw and loss probabilities while preserving <code>W + D/2 = E</code>:</p>
          <div class="formula">D = pD(y)·4E(1−E)<br>W = E−D/2<br>L = 1−E−D/2</div>
          <p>NFELO integrates over the uncertainty in the strength difference, then calibrates friendly and competitive forecasts separately. A forecast-only score model also tracks whether each team has recently scored or conceded more than its strength alone would suggest. The current or selected-date attack and defence tendencies are available in an expandable section on each team page.</p>
          <p>The scoring layer changes probabilities only. It is allowed to move towards its score-based forecast only as far as it can go without reversing the network model’s most likely win, draw or loss.</p>
          <details class="method-details">
            <summary>Attack, defence and annual calibration</summary>
            <p>The goal environment uses the current and preceding ${number(f.goal_environment_years)} calendar years, with a ${number(f.goal_prior_matches)}-match prior at ${number(f.goal_prior_per_team, 2)} goals per team:</p>
            <div class="formula">B = [${number(2 * f.goal_prior_matches * f.goal_prior_per_team, 0)} + previous goals] / [${number(2 * f.goal_prior_matches)} + 2(previous matches)]<br>g = ${number(f.parameters.gap_scale, 1)} ln[E/(1−E)]<br>λ₁ = B exp(g/2+A₁−D₂)<br>λ₂ = B exp(−g/2+A₂−D₁)</div>
            <p>Attack and defence residuals decay as <code>exp(−${number(f.parameters.annual_decay, 1)}t)</code> and learn with rate ${number(f.parameters.learning_rate, 2)} after every forecast on the date has been stored.</p>
            <div class="formula">Ppool = ${number(f.calibration.nfelo_weight, 4)}Pnetwork + ${number(f.calibration.score_weight, 4)}Pscore<br>Pfinal = Pnetwork + t(Ppool−Pnetwork)</div>
            <p>At each January boundary, the draw adjustment, probability powers and pool weight are fitted from only the preceding ${number(f.calibration_window_years)} complete years. For ${yearNumber(f.calibration.year)}, that means ${number(f.calibration.training_matches)} matches from ${yearNumber(f.calibration.training_first_year)}–${yearNumber(f.calibration.training_last_year)}. Coefficients are fixed to ${number(f.calibration_precision_decimals)} decimal places before use.</p>
          </details>
          <details class="method-details">
            <summary>Exact-score table</summary>
            <p>Poisson score probabilities are reconciled to the displayed W/D/L totals. Within each outcome region <code>o</code>:</p>
            <div class="formula">P*(i,j) = Praw(i,j) · Pfinal(o) / Praw(o)</div>
            <p>This preserves the relative scorelines within wins, draws and losses while making the complete grid agree with the headline forecast.</p>
          </details>
        </section>

        <section class="method-section" aria-labelledby="method-learning">
          <h2 id="method-learning" tabindex="-1">Learning from results</h2>
          <p>A surprising result carries more information than an expected one. Goal margin also matters, but additional goals have diminishing influence and the margin is adjusted for the scoring environment of its era.</p>
          <details class="method-details">
            <summary>Goal-margin formula</summary>
            <p>The recent excess-margin environment <code>e</code> uses the match year and preceding ${number(p.goal_margin.lookback_years)} calendar years, with a ${number(p.goal_margin.prior_decisive_matches)}-match prior:</p>
            <div class="formula">e = [${number(p.goal_margin.prior_decisive_matches)}·${number(p.goal_margin.prior_excess_goals, 2)} + Σ(min(|mᵣ|,7)−1)] / [${number(p.goal_margin.prior_decisive_matches)} + n]<br>u = min{7, 1 + [min(|m|,7)−1]·[${number(p.goal_margin.prior_excess_goals, 2)}/max(0.10,e)]^${number(p.goal_margin.environment_power, 10)}}</div>
            <div class="formula">G(0) = ${number(p.goal_margin.draw, 10)}<br>G(m) = 1, if u ≤ 1<br>G(m) = 1 + (u−1)(${number(p.goal_margin.two, 10)}−1), if 1 &lt; u ≤ 2<br>G(m) = ${number(p.goal_margin.two, 10)} + (u−2)(${number(p.goal_margin.three, 10)}−${number(p.goal_margin.two, 10)}), if 2 &lt; u ≤ 3<br>G(m) = ${number(p.goal_margin.three, 10)} + ${number(p.goal_margin.tail, 10)}(u−3), if u &gt; 3</div>
          </details>
          <details class="method-details">
            <summary>Joint matchday update</summary>
            <p>For match <code>k</code>, <code>xₖ=e₁−e₂</code>, <code>βₖ=a(y)ln(10)/400</code>, and <code>qₖ</code> is ${p.network.friendly_information_ratio_exact} for an evidence-backed friendly or 1 otherwise:</p>
            <div class="formula">λₖ = ${number(p.network.quality_scale, 6)}G(mₖ)qₖ<br>cₖ = λₖβₖ²Eₖ(1−Eₖ)<br>gₖ = xₖλₖβₖ(Sₖ−Eₖ)<br>Σ′ = [Σ⁻¹ + Σₖcₖxₖxₖᵀ]⁻¹<br>μ′ = μ + Σ′Σₖgₖ</div>
            <p>All matches on the date enter one update, making the result independent of arbitrary row order.</p>
          </details>
          <p>Confirmed friendlies use exactly <b>${p.network.friendly_information_ratio_exact}</b> of the network information assigned to competitive matches. This is not a direct multiplier on visible rating points. Constant, stepped and smoothly changing friendly weights were tested; the more complicated era-based versions did not improve the later confirmation period, so the single coefficient was retained.</p>
        </section>

        <section class="method-section" aria-labelledby="method-ratings">
          <h2 id="method-ratings" tabindex="-1">The published rating</h2>
          <p>The public rating starts from underlying strength, anchors it to the leading active international pool, then reduces it when recent opponent breadth is narrow or uncertainty is high:</p>
          <div class="formula">Nᵢ = (Σⱼwᵢⱼ)² / Σⱼwᵢⱼ²<br>ρᵢ = Nᵢ/(Nᵢ+4)<br>Mᵢ = 2000 + ρᵢ(μᵢ−B)<br>NRᵢ = Mᵢ − 1.644854√Σᵢᵢ</div>
          <p><code>B</code> is the mean underlying strength of the ten strongest eligible active teams. Opponent evidence decays with age, repeated opponents are combined, and <code>Nᵢ</code> is the effective variety of opponents.</p>
          <p>This same rating powers current and historical rankings, tournament snapshots, team pages, peaks and record tables. Teams need 30 previous matches to receive a displayed rating, and must have played within the relevant activity window to appear in a ranking.</p>
          <p>The forecast deliberately uses more information than this one number. Therefore a slightly lower-rated team can be favoured in a particular match because of uncertainty, venue or attack and defence tendencies. The rating answers “how strong is the evidence-supported ranking estimate?”; the forecast answers “what is most likely in this matchup?”</p>
          <p>For an eligible match record, combined rating is:</p>
          <div class="formula">Qᵢⱼ = Mᵢ+Mⱼ−1.644854√(Σᵢᵢ+Σⱼⱼ+2Σᵢⱼ)</div>
        </section>

        <section class="method-section" aria-labelledby="method-validation">
          <h2 id="method-validation" tabindex="-1">Evidence and forecast accuracy</h2>
          <p>The first row is the exact result for the formula the site currently runs, replayed over every stored pre-match forecast from 1960 through ${validDate(replay.cutoff)}. Lower log loss means better use of all three probabilities; top-choice accuracy counts only whether the most likely win, draw or loss happened.</p>
          <div class="table-hint" aria-hidden="true">Swipe horizontally to see every column →</div>
          <div class="table-shell parameter-table"><table><thead><tr><th>Model</th><th>Test basis</th><th class="numeric">Forecasts</th><th class="numeric">Log loss</th><th class="numeric">Top W/D/L correct</th></tr></thead><tbody>
            <tr><td><b>Current deployed NFELO formula</b></td><td>Final-formula replay</td><td class="numeric">${number(replay.matches)}</td><td class="numeric"><b>${number(replay.log_loss, 6)}</b></td><td class="numeric"><b>${precisePercent(replay.accuracy)}</b></td></tr>
            <tr><td>Earlier NFELO network benchmark</td><td>Five-block historical holdout</td><td class="numeric">${number(benchmark.matches)}</td><td class="numeric">${number(benchmark.log_loss, 6)}</td><td class="numeric">${precisePercent(benchmark.accuracy)}</td></tr>
            <tr><td>Best tested scalar Elo</td><td>Same historical holdout</td><td class="numeric">${number(benchmark.matches)}</td><td class="numeric">${number(benchmark.best_scalar_elo_log_loss, 6)}</td><td class="numeric">${precisePercent(benchmark.best_scalar_elo_accuracy)}</td></tr>
            <tr><td>G-Elo comparison</td><td>Same historical holdout</td><td class="numeric">${number(benchmark.matches)}</td><td class="numeric">${number(benchmark.g_elo_log_loss, 6)}</td><td class="numeric">${precisePercent(benchmark.g_elo_accuracy)}</td></tr>
            <tr><td>Published World Football Elo forecast</td><td>Same historical holdout</td><td class="numeric">${number(benchmark.matches)}</td><td class="numeric">${number(benchmark.published_wfe_log_loss, 6)}</td><td class="numeric">${precisePercent(benchmark.published_wfe_accuracy)}</td></tr>
          </tbody></table></div>
          <p>The four holdout rows form the like-for-like comparison: model choices used earlier periods and were scored on later ones. The current-formula row instead applies today’s final constants throughout history, so it verifies the deployed implementation but should not be read as a clean head-to-head improvement over those older benchmark rows.</p>
          <p>Formula changes are selected with earlier data and checked on later periods before adoption. Identified future fixtures are also stored before their results are known, building a genuinely prospective record alongside the historical tests.</p>
        </section>

        <section class="method-section" aria-labelledby="method-limits">
          <h2 id="method-limits" tabindex="-1">Reproducibility and limits</h2>
          <p>The repository records the model configuration, source ledger, research code and first-published prospective forecast for every identified future fixture. Routine data updates rebuild the chronology but do not silently refit structural rating parameters; annual probability calibration follows its declared prior-years-only rule.</p>
          <p>NFELO uses results, scores, dates, venues and competition class. It does not know line-ups, injuries, red cards, tactics, travel, rest, weather or betting markets. Historical team lineages are modelling choices, and cross-era ratings cannot prove how teams separated by decades would perform head to head.</p>
          <p>Probabilities are estimates, not certainties or betting advice. The complete research record and reproducible checks are available in the <a href="https://github.com/nfelo/nfelo.github.io/tree/main/research" rel="external">repository’s research directory</a>.</p>
        </section>
      </article>`;

    const requestedSection = query.get("section");
    const validSections = new Set([
      "overview",
      "strength",
      "venue",
      "forecast",
      "learning",
      "ratings",
      "validation",
      "limits",
    ]);
    if (validSections.has(requestedSection)) {
      const target = document.getElementById(`method-${requestedSection}`);
      window.requestAnimationFrame(() => {
        target?.scrollIntoView({ block: "start" });
        target?.focus({ preventScroll: true });
      });
    }
  }

  function renderAbout() {
    setTitle("About");
    const update = summary.meta.source_update || {};
    content.innerHTML = `
      <div class="page page-narrow">
        <p class="eyebrow">Data · updates · limitations</p><h1>About</h1>
        <p class="lede">Network Football Elo is an independent, results-only international football strength and prediction system. It covers senior men's internationals from 1872 to the present and publishes its evidence limits alongside its results.</p>
        <section class="section split">
          <div class="panel"><p class="eyebrow">Results included through</p><h2>${validDate(summary.meta.results_through)}</h2><p>${number(summary.meta.matches)} matches across ${number(summary.meta.teams)} team histories.</p><p class="muted small">Data checked: ${update.source_checked_at ? validTimestamp(update.source_checked_at) : validDate(summary.meta.results_through)}<br>Site generated: ${validTimestamp(summary.meta.generated_at)}</p></div>
          <div class="panel panel-dark"><p class="eyebrow">Automatic updates</p><h2>Checked three times daily.</h2><p class="muted">Results and fixtures are checked after the main Americas, Asia/Oceania and Europe/Africa match windows. Each update is validated and the complete rating history is rebuilt before publication. If new data fails validation, the existing site remains online unchanged.</p></div>
        </section>
        <article class="section prose">
          <h2>Data sources</h2>
          <p>Historical results and team labels are based on <a href="https://eloratings.net/" rel="external">World Football Elo Ratings</a>. The <a href="https://github.com/nfelo/nfelo.github.io" rel="external">source code and build history are available on GitHub</a>. Recent results use the CC0-licensed <a href="https://github.com/martj42/international_results" rel="external">international_results dataset</a> and the public-domain <a href="https://github.com/openfootball/worldcup.json" rel="external">OpenFootball World Cup feed</a>. Future fixtures use World Football Elo Ratings' cross-confederation schedule, supplemented by <a href="https://www.thesportsdb.com/" rel="external">TheSportsDB</a> for richer competition details. Duplicate events are merged and conflicting scores stop publication.</p>
          <h2>Automatic updates</h2>
          <p>When new results arrive, the entire history is recalculated by complete matchday. Every match on a known date is forecast from the same frozen strength, scoring and country-venue states, then all of that date's evidence is learned. Rating parameters and the forecast-layer structure remain fixed during routine updates. Once each January, probability calibration is refitted from the preceding eight complete calendar years; this does not alter strength ratings or the country-venue formula.</p>
          <h2>One rating across the whole site</h2>
          <p>Current and historical rankings, tournament snapshots, nation peaks and every record table all use the same evidence-adjusted NFELO formula. History is reconstructed from compact global network snapshots, so a connected team’s rating can reflect other teams’ results even when it did not play that day. The latest History table and Current Rankings are checked for identical membership, order and displayed values on every build.</p>
          <h2>Teams covered</h2>
          <p>The source ledger covers senior international histories rather than FIFA membership alone, so it includes some territories, regional selections and defunct teams. Every listed team is subject to the same match-count, activity, opponent-breadth and uncertainty rules. Inclusion is a data-scope decision, not a statement about political status or competition eligibility.</p>
          <h2>Current accuracy figure</h2>
          <p>Across ${number(summary.validation.retrospective.matches)} historical pre-match forecasts through ${validDate(summary.validation.retrospective.cutoff)}, the current formula’s most likely win, draw or loss was correct ${percent(summary.validation.retrospective.accuracy)} of the time. This is a retrospective full-history replay, not a promise about one future match. <a href="#/methodology?section=validation">See the exact technical result →</a></p>
          <h2>Prospective record</h2>
          <p>For every identified future fixture and methodology version, the first published probability vector is appended to an immutable repository ledger. Later results can therefore be scored against a forecast that was genuinely recorded beforehand rather than reconstructed with hindsight.</p>
          <h2>What the model does not know</h2>
          <p>It does not use line-ups, player availability, injuries, red cards, travel, rest, tactical matchups, weather or betting markets. Its probabilities describe the historical-information model, not certainty and not a recommendation to wager.</p>
          <h2>Quality checks</h2>
          <p>Every update checks the source format, row count, dates, scores, team names, probability sums, date-order and team-order invariance, covariance validity, venue-state bounds, neutral-site behaviour, score-grid reconciliation and historical peak guardrails. The site is published only after the complete rebuild and automated test suite pass.</p>
        </article>
      </div>`;
  }

  function renderNotFound() {
    setTitle("Not found");
    content.innerHTML = `<div class="error-panel"><p class="eyebrow">404</p><h2>Page not found</h2><p>Return to a main section below.</p><div class="context-actions"><a class="button button-dark" href="#/rankings">Rankings</a><a class="button button-quiet" href="#/matches">Matches</a><a class="button button-quiet" href="#/">Home</a></div></div>`;
  }

  async function route({
    scrollMode = "preserve",
    scrollY = null,
  } = {}) {
    disposeRatingHistoryCharts();
    const current = parseRoute();
    setActiveNav(current.section);
    try {
      if (!summary) [summary, catalog] = await Promise.all([getJSON("data/summary.json"), getJSON("data/catalog.json")]);
      if (!teamAliasSearch.size) initialiseTeamAliasSearch();
      switch (current.section) {
        case "home": await renderHome(); break;
        case "rankings": renderRankings(current); break;
        case "history": await renderHistory(current); break;
        case "tournaments": await renderTournaments(current); break;
        case "matches": await renderMatches(current); break;
        case "fixtures": await renderFixtures(current); break;
        case "records": renderRecords(current); break;
        case "compare": await renderCompare(current); break;
        case "predict": await renderPredict(current); break;
        case "team": current.value ? await renderTeam(current.value, current.query) : renderNotFound(); break;
        case "methodology": renderMethodology(current.query); break;
        case "faq": renderFAQ(); break;
        case "about": renderAbout(); break;
        default: renderNotFound();
      }
      setRouteMetadata(current);
      if (location.hash.startsWith("#/")) {
        history.replaceState(
          routeHistoryState(
            scrollMode === "top"
              ? 0
              : currentScrollY(),
          ),
          "",
          cleanRouteURL(
            current.section,
            current.value,
            current.query,
          ),
        );
      }
      window.goatcounter?.count?.({
        path: location.pathname + location.search,
        title: document.title,
      });
      content.focus({ preventScroll: true });
      const methodologyHandlesScroll = (
        current.section === "methodology"
        && current.query.has("section")
      );
      if (!methodologyHandlesScroll && scrollMode !== "preserve") {
        const targetScroll = scrollMode === "restore"
          ? Math.max(0, Number(scrollY) || 0)
          : 0;
        window.requestAnimationFrame(() => {
          window.scrollTo({
            top: targetScroll,
            left: 0,
            behavior: "auto",
          });
        });
      }
      window.__nfeloBoot.ready = true;
    } catch (error) {
      console.error(error);
      window.__nfeloBoot.failed = true;
      content.innerHTML = `<div class="error-panel" role="alert"><p class="eyebrow">Build data unavailable</p><h2>The static rating files could not be loaded.</h2><p>${escapeHTML(error.message)}</p><button class="button button-dark" type="button" id="retry">Retry</button></div>`;
      document.getElementById("retry")?.addEventListener("click", () => { dataCache.clear(); summary = null; route(); });
    }
  }

  nav?.querySelectorAll(".nav-group").forEach((group) => {
    group.addEventListener("toggle", () => {
      if (!group.open) return;
      nav.querySelectorAll(".nav-group[open]").forEach((other) => {
        if (other !== group) other.removeAttribute("open");
      });
    });
  });
  nav?.addEventListener?.("click", (event) => {
    if (event.target.closest("a")) closeNavigation();
  });
  menuButton?.addEventListener("click", () => {
    if (nav?.classList.contains("is-open")) {
      closeNavigation();
      return;
    }
    nav?.classList.add("is-open");
    menuButton.setAttribute("aria-expanded", "true");
  });
  document.addEventListener("click", (event) => {
    const routeLink = event.target.closest?.('a[href^="#/"]');
    const targetRoute = routeFromInternalHref(
      routeLink?.getAttribute("href"),
    );
    const plainPrimaryClick = (
      !event.defaultPrevented
      && (event.button == null || event.button === 0)
      && !event.metaKey
      && !event.ctrlKey
      && !event.shiftKey
      && !event.altKey
    );
    if (
      targetRoute
      && plainPrimaryClick
      && !routeLink.hasAttribute("download")
      && routeLink.getAttribute("target") !== "_blank"
    ) {
      event.preventDefault();
      navigateToInternalRoute(targetRoute);
    }
    if (
      !nav?.contains(event.target)
      && event.target !== menuButton
      && (
        nav?.classList.contains("is-open")
        || nav?.querySelector(".nav-group[open]")
      )
    ) {
      closeNavigation();
    }
  });
  document.addEventListener("keydown", (event) => {
    if (event.key !== "Escape") return;
    if (nav?.classList.contains("is-open")) {
      closeNavigation(true);
      return;
    }
    const openGroup = nav?.querySelector(".nav-group[open]");
    if (!openGroup) return;
    openGroup.removeAttribute("open");
    openGroup.querySelector("summary")?.focus();
  });
  if ("scrollRestoration" in history) {
    history.scrollRestoration = "manual";
  }
  window.addEventListener(
    "hashchange",
    () => route({ scrollMode: "top" }),
  );
  window.addEventListener("popstate", (event) => {
    route({
      scrollMode: "restore",
      scrollY: event.state?.nfeloScrollY,
    });
  });
  route();
})();
