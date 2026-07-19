#include <algorithm>
#include <array>
#include <chrono>
#include <cmath>
#include <cstdint>
#include <fstream>
#include <iomanip>
#include <iostream>
#include <limits>
#include <numeric>
#include <sstream>
#include <stdexcept>
#include <string>
#include <unordered_set>
#include <unordered_map>
#include <vector>

struct Match {
    int id, day, year, month, dom, a, b, ga, gb, home, friendly, level, official_a, official_b;
    double result() const { return ga > gb ? 1.0 : ga < gb ? 0.0 : 0.5; }
    int margin() const { return std::abs(ga - gb); }
    int outcome() const { return ga > gb ? 0 : ga == gb ? 1 : 2; }
};

struct Parameters {
    double prior_sd = 300.0;
    double drift_sd = 19.750212594949737;
    double quality = 1.7440260583320362;
    double friendly_ratio = 1.0;
    double competitive_temperature = 1.0635626456560392;
    double friendly_temperature = 0.9697407083655329;
    bool constant_observation = false;
    double constant_scale = 1.0;
    double constant_home = 85.0;
    double constant_draw = 0.30;
    bool diagonal = false;
    bool batch_predict_day = false;
    bool simultaneous_day_update = false;
    bool joint_debut = false;
    bool day_debut = false;
    bool track_records = false;
    std::string margin = "current";
    int score_first_year = 1960;
    int score_last_day = 2026 * 400 + 7 * 32 + 11;
    bool fit_temperatures = false;
    int fit_first_year = 1940;
    int fit_last_day = 1959 * 400 + 399;
    std::string output;
};

static constexpr std::array<int, 5> KNOT_YEARS{1900, 1930, 1960, 1990, 2020};
static constexpr std::array<double, 5> SCALE{
    1.9329803161851784, 1.5602143637570678, 1.3044459799655215, 1.1218570234757215, 1.0};
static constexpr std::array<double, 5> HOME{
    73.123115543503, 96.74246793815797, 112.89558566270792, 112.66052421548639, 83.53363897913016};
static constexpr std::array<double, 5> DRAW{
    0.18451738305372078, 0.2174334339602218, 0.25965582882029153, 0.30867595078868215,
    0.32513463832148676};
static constexpr double G_DRAW = 3.486642593835564;
static constexpr double G_TWO = 1.755270459152449;
static constexpr double G_THREE = 2.20104735688078;
static constexpr double G_TAIL = 1.467767822525712;
static constexpr double MARGIN_POWER = 1.880272889370813;
static constexpr double NEWCOMER_OFFSET = -192.90021991733568;
static constexpr double ACTIVE_POOL_SLOPE = -84.24860586823341;
static constexpr std::array<double, 11> NODES{
    -3.6684708465595826, -2.7832900997816514, -2.0259480158257555, -1.3265570844949328,
    -0.6568095668820998, 0.0, 0.6568095668820998, 1.3265570844949328, 2.0259480158257555,
    2.7832900997816514, 3.6684708465595826};
static constexpr std::array<double, 11> WEIGHTS{
    0.0000008121849790214923, 0.00019567193027122338, 0.0067202852355372645,
    0.06613874607105782, 0.24224029987396992, 0.36940836940836935,
    0.24224029987396992, 0.06613874607105782, 0.0067202852355372645,
    0.00019567193027122338, 0.0000008121849790214923};

double linear_interpolate(int year, const std::array<double, 5>& values) {
    if (year <= KNOT_YEARS.front()) return values.front();
    if (year >= KNOT_YEARS.back()) return values.back();
    int right = 1;
    while (year > KNOT_YEARS[right]) ++right;
    int left = right - 1;
    double fraction = double(year - KNOT_YEARS[left]) / double(KNOT_YEARS[right] - KNOT_YEARS[left]);
    return values[left] + fraction * (values[right] - values[left]);
}

double era_scale(int year) {
    std::array<double, 5> logs{};
    for (int i = 0; i < 5; ++i) logs[i] = std::log(SCALE[i]);
    return std::exp(linear_interpolate(year, logs));
}

double home_advantage(int year) { return linear_interpolate(year, HOME); }

double draw_probability(int year) {
    std::array<double, 5> transformed{};
    for (int i = 0; i < 5; ++i) {
        double unit = (DRAW[i] - 0.05) / 0.40;
        transformed[i] = std::log(unit / (1.0 - unit));
    }
    double logit = linear_interpolate(year, transformed);
    return 0.05 + 0.40 / (1.0 + std::exp(-logit));
}

double model_scale(int year, const Parameters& parameters) {
    return parameters.constant_observation ? parameters.constant_scale : era_scale(year);
}

double model_home(int year, const Parameters& parameters) {
    return parameters.constant_observation ? parameters.constant_home : home_advantage(year);
}

double model_draw(int year, const Parameters& parameters) {
    return parameters.constant_observation ? parameters.constant_draw : draw_probability(year);
}

inline double logistic10(double value) { return 1.0 / (1.0 + std::pow(10.0, -value / 400.0)); }

std::array<double, 3> probabilities(double difference, double variance, int year, bool friendly,
                                    const Parameters& parameters) {
    double scale = model_scale(year, parameters);
    double sd = scale * std::sqrt(std::max(0.0, variance));
    double win = 0.0, draw = 0.0, loss = 0.0;
    for (int k = 0; k < 11; ++k) {
        double expectation = logistic10(difference + std::sqrt(2.0) * sd * NODES[k]);
        double d = model_draw(year, parameters) * 4.0 * expectation * (1.0 - expectation);
        win += WEIGHTS[k] * (expectation - 0.5 * d);
        draw += WEIGHTS[k] * d;
        loss += WEIGHTS[k] * (1.0 - expectation - 0.5 * d);
    }
    double temperature = friendly ? parameters.friendly_temperature : parameters.competitive_temperature;
    win = std::pow(std::max(1e-15, win), temperature);
    draw = std::pow(std::max(1e-15, draw), temperature);
    loss = std::pow(std::max(1e-15, loss), temperature);
    double total = win + draw + loss;
    return {win / total, draw / total, loss / total};
}

double margin_weight(int margin, double environment, const Parameters& parameters) {
    if (parameters.margin == "none") return 1.0;
    if (parameters.margin == "log") return margin == 0 ? 1.0 : 1.0 + std::log(double(std::min(margin, 7)));
    if (parameters.margin == "sqrt") return margin == 0 ? 1.0 : std::sqrt(double(std::min(margin, 7)));
    if (parameters.margin == "wfe") {
        if (margin == 0 || margin == 1) return 1.0;
        if (margin == 2) return 1.5;
        if (margin == 3) return 1.75;
        return 1.75 + (double(margin) - 3.0) / 8.0;
    }
    if (margin == 0) return G_DRAW;
    double raw = std::min(margin, 7);
    double effective = 1.0 + (raw - 1.0) * std::pow(1.10 / std::max(0.10, environment), MARGIN_POWER);
    effective = std::min(7.0, effective);
    if (effective <= 1.0) return 1.0;
    if (effective <= 2.0) return 1.0 + (effective - 1.0) * (G_TWO - 1.0);
    if (effective <= 3.0) return G_TWO + (effective - 2.0) * (G_THREE - G_TWO);
    return G_THREE + G_TAIL * (effective - 3.0);
}

std::vector<Match> read_matches(const std::string& path, int& team_count) {
    std::ifstream input(path);
    if (!input) throw std::runtime_error("cannot open " + path);
    std::vector<Match> result;
    std::string line;
    team_count = 0;
    while (std::getline(input, line)) {
        if (line.empty() || line[0] == '#') continue;
        std::istringstream row(line);
        Match match{};
        row >> match.id >> match.day >> match.year >> match.month >> match.dom >> match.a >> match.b >>
            match.ga >> match.gb >> match.home >> match.friendly >> match.level >> match.official_a >> match.official_b;
        if (!row) throw std::runtime_error("invalid match row");
        result.push_back(match);
        team_count = std::max(team_count, std::max(match.a, match.b) + 1);
    }
    return result;
}

class NetworkModel {
public:
    NetworkModel(int count, Parameters parameters)
        : n(count), par(std::move(parameters)), mean(n, std::numeric_limits<double>::quiet_NaN()),
          covariance(par.diagonal ? n : n * n, 0.0), games(n, 0), last_year(n, -10000),
          last_day(n, -1), breadth_day(n, -1), opponent_weights(n) {}

    bool initialised(int team) const { return !std::isnan(mean[team]); }

    std::vector<int> active(int year, int years) const {
        std::vector<int> values;
        for (int i = 0; i < n; ++i)
            if (initialised(i) && year - last_year[i] <= years) values.push_back(i);
        return values;
    }

    double debut_mean(int year) const {
        auto pool = active(year, 4);
        std::vector<double> mature, established;
        for (int i : pool) {
            if (games[i] >= 30) mature.push_back(mean[i]);
            if (games[i] >= 10) established.push_back(mean[i]);
        }
        auto& reference = mature.size() >= 5 ? mature : established;
        if (reference.empty()) return 0.0;
        std::sort(reference.begin(), reference.end());
        int middle = int(reference.size() / 2);
        double median = reference.size() % 2 ? reference[middle] : 0.5 * (reference[middle - 1] + reference[middle]);
        return median + NEWCOMER_OFFSET + ACTIVE_POOL_SLOPE * std::log((pool.size() + 10.0) / 50.0);
    }

    void initialise_with(int team, int day, double value) {
        if (initialised(team)) return;
        mean[team] = value;
        covariance[index(team, team)] = par.prior_sd * par.prior_sd;
        last_day[team] = day;
        breadth_day[team] = day;
    }

    void initialise_pair(const Match& match) {
        bool new_a = !initialised(match.a), new_b = !initialised(match.b);
        if (par.joint_debut && new_a && new_b) {
            double value = debut_mean(match.year);
            initialise_with(match.a, match.day, value);
            initialise_with(match.b, match.day, value);
            return;
        }
        if (new_a) initialise_with(match.a, match.day, debut_mean(match.year));
        if (new_b) initialise_with(match.b, match.day, debut_mean(match.year));
    }

    void add_drift(int team, int day) {
        double elapsed = std::max(0.0, double(day - last_day[team]) / 400.0);
        covariance[index(team, team)] += par.drift_sd * par.drift_sd * elapsed;
        last_day[team] = day;
    }

    void decay_breadth(int team, int day) {
        if (!par.track_records) return;
        int previous = breadth_day[team];
        if (previous < 0) { breadth_day[team] = day; return; }
        double elapsed = std::max(0.0, double(day - previous) / 400.0);
        double factor = std::pow(0.5, elapsed / 8.0);
        if (factor < 1.0) {
            auto& values = opponent_weights[team];
            for (auto iterator = values.begin(); iterator != values.end();) {
                iterator->second *= factor;
                if (iterator->second < 1e-10) iterator = values.erase(iterator);
                else ++iterator;
            }
        }
        breadth_day[team] = day;
    }

    std::pair<double, double> breadth(int team) const {
        double total = 0.0, squares = 0.0;
        for (const auto& [opponent, value] : opponent_weights[team]) { total += value; squares += value * value; }
        double effective = squares > 0.0 ? total * total / squares : 0.0;
        return {effective, effective / (effective + 4.0)};
    }

    double reference(int year, int include_a, int include_b) const {
        std::vector<double> values;
        for (int team = 0; team < n; ++team) {
            bool eligible = initialised(team) && games[team] >= 30 && year - last_year[team] <= 8;
            if ((team == include_a || team == include_b) && games[team] >= 30) eligible = true;
            if (eligible) values.push_back(mean[team]);
        }
        if (values.size() < 2) return std::numeric_limits<double>::quiet_NaN();
        std::sort(values.begin(), values.end(), std::greater<double>());
        int count = std::min<int>(10, values.size());
        return std::accumulate(values.begin(), values.begin() + count, 0.0) / count;
    }

    std::array<double, 4> record_values(int team, double baseline) const {
        auto [effective, reliability] = breadth(team);
        double adjusted_mean = 2000.0 + reliability * (mean[team] - baseline);
        double se = std::sqrt(std::max(0.0, covariance[index(team, team)]));
        return {adjusted_mean, se, effective, reliability};
    }

    struct Forecast { std::array<double, 3> p; double expected, difference, variance; };

    Forecast predict(const Match& match) const {
        double scale = model_scale(match.year, par);
        double difference = scale * (mean[match.a] - mean[match.b]) + model_home(match.year, par) * match.home;
        double expected = logistic10(difference);
        double variance = covariance[index(match.a, match.a)] + covariance[index(match.b, match.b)];
        if (!par.diagonal) variance -= 2.0 * covariance[index(match.a, match.b)];
        return {probabilities(difference, std::max(0.0, variance), match.year, bool(match.friendly), par),
                expected, difference, std::max(0.0, variance)};
    }

    void update(const Match& match, double environment) {
        auto forecast = predict(match);
        double weight = par.quality * margin_weight(match.margin(), environment, par) *
                        (match.friendly ? par.friendly_ratio : 1.0);
        double beta = std::log(10.0) * model_scale(match.year, par) / 400.0;
        double information = std::max(1e-8, forecast.expected * (1.0 - forecast.expected));
        double curvature = weight * beta * beta * information;
        double denominator = 1.0 + curvature * forecast.variance;
        double mean_factor = weight * beta * (match.result() - forecast.expected) / denominator;
        double covariance_factor = curvature / denominator;
        if (par.diagonal) {
            double va = covariance[match.a], vb = covariance[match.b];
            mean[match.a] += va * mean_factor;
            mean[match.b] -= vb * mean_factor;
            covariance[match.a] -= va * va * covariance_factor;
            covariance[match.b] -= vb * vb * covariance_factor;
        } else {
            direction.resize(n);
            for (int i = 0; i < n; ++i)
                direction[i] = covariance[index(i, match.a)] - covariance[index(i, match.b)];
            for (int i = 0; i < n; ++i) mean[i] += direction[i] * mean_factor;
            for (int i = 0; i < n; ++i) {
                double left = direction[i] * covariance_factor;
                #pragma GCC ivdep
                for (int j = 0; j < n; ++j)
                    covariance[index(i, j)] -= left * direction[j];
            }
        }
        ++games[match.a]; ++games[match.b];
        last_year[match.a] = match.year; last_year[match.b] = match.year;
        if (par.track_records) {
            opponent_weights[match.a][match.b] += 1.0;
            opponent_weights[match.b][match.a] += 1.0;
        }
    }

    void update_day_simultaneous(const std::vector<Match>& matches, std::size_t start,
                                 std::size_t end, double environment) {
        // One frozen linearisation for the whole date. The covariance update
        // is the joint Gaussian precision update; the mean uses the final
        // covariance times the sum of all frozen score vectors. This removes
        // arbitrary within-date order from the approximate posterior.
        std::vector<double> score(n, 0.0);
        struct Observation { int a, b; double curvature; };
        std::vector<Observation> observations;
        observations.reserve(end - start);
        for (std::size_t k = start; k < end; ++k) {
            const auto& match = matches[k];
            auto forecast = predict(match);
            double weight = par.quality * margin_weight(match.margin(), environment, par) *
                            (match.friendly ? par.friendly_ratio : 1.0);
            double beta = std::log(10.0) * model_scale(match.year, par) / 400.0;
            double information = std::max(1e-8, forecast.expected * (1.0 - forecast.expected));
            observations.push_back({match.a, match.b, weight * beta * beta * information});
            double gradient = weight * beta * (match.result() - forecast.expected);
            score[match.a] += gradient;
            score[match.b] -= gradient;
        }
        if (par.diagonal) {
            // The diagonal family deliberately discards cross-team terms. A
            // frozen precision update is nevertheless invariant to row order.
            for (const auto& item : observations) {
                double va = covariance[item.a], vb = covariance[item.b];
                covariance[item.a] = 1.0 / (1.0 / va + item.curvature);
                covariance[item.b] = 1.0 / (1.0 / vb + item.curvature);
            }
            for (int team = 0; team < n; ++team) mean[team] += covariance[team] * score[team];
        } else {
            for (const auto& item : observations) {
                direction.resize(n);
                for (int i = 0; i < n; ++i)
                    direction[i] = covariance[index(i, item.a)] - covariance[index(i, item.b)];
                double variance = covariance[index(item.a, item.a)] + covariance[index(item.b, item.b)]
                                  - 2.0 * covariance[index(item.a, item.b)];
                double factor = item.curvature / (1.0 + item.curvature * std::max(0.0, variance));
                for (int i = 0; i < n; ++i) {
                    double left = direction[i] * factor;
                    #pragma GCC ivdep
                    for (int j = 0; j < n; ++j)
                        covariance[index(i, j)] -= left * direction[j];
                }
            }
            direction.assign(n, 0.0);
            for (int i = 0; i < n; ++i) {
                double value = 0.0;
                for (int j = 0; j < n; ++j) value += covariance[index(i, j)] * score[j];
                direction[i] = value;
            }
            for (int i = 0; i < n; ++i) mean[i] += direction[i];
        }
        for (std::size_t k = start; k < end; ++k) {
            const auto& match = matches[k];
            ++games[match.a]; ++games[match.b];
            last_year[match.a] = match.year; last_year[match.b] = match.year;
            if (par.track_records) {
                opponent_weights[match.a][match.b] += 1.0;
                opponent_weights[match.b][match.a] += 1.0;
            }
        }
    }

    int game_count(int team) const { return games[team]; }
    double team_mean(int team) const { return mean[team]; }
    double team_variance(int team) const { return covariance[index(team, team)]; }

private:
    int n;
    Parameters par;
    std::vector<double> mean, covariance, direction;
    std::vector<int> games, last_year, last_day, breadth_day;
    std::vector<std::unordered_map<int, double>> opponent_weights;
    std::size_t index(int i, int j) const { return par.diagonal ? std::size_t(i) : std::size_t(i) * n + j; }
};

Parameters parse_parameters(int argc, char** argv, std::string& input) {
    if (argc < 2) throw std::runtime_error("usage: network_eval MATCHES.tsv [options]");
    input = argv[1];
    Parameters p;
    for (int i = 2; i < argc; ++i) {
        std::string key = argv[i];
        auto value = [&]() -> std::string {
            if (++i >= argc) throw std::runtime_error("missing value for " + key);
            return argv[i];
        };
        if (key == "--prior") p.prior_sd = std::stod(value());
        else if (key == "--drift") p.drift_sd = std::stod(value());
        else if (key == "--quality") p.quality = std::stod(value());
        else if (key == "--friendly-ratio") p.friendly_ratio = std::stod(value());
        else if (key == "--friendly-temperature") p.friendly_temperature = std::stod(value());
        else if (key == "--competitive-temperature") p.competitive_temperature = std::stod(value());
        else if (key == "--constant-scale") { p.constant_observation = true; p.constant_scale = std::stod(value()); }
        else if (key == "--constant-home") { p.constant_observation = true; p.constant_home = std::stod(value()); }
        else if (key == "--constant-draw") { p.constant_observation = true; p.constant_draw = std::stod(value()); }
        else if (key == "--margin") p.margin = value();
        else if (key == "--score-first-year") p.score_first_year = std::stoi(value());
        else if (key == "--score-last-day") p.score_last_day = std::stoi(value());
        else if (key == "--fit-first-year") p.fit_first_year = std::stoi(value());
        else if (key == "--fit-last-day") p.fit_last_day = std::stoi(value());
        else if (key == "--output") p.output = value();
        else if (key == "--diagonal") p.diagonal = true;
        else if (key == "--batch-predict-day") p.batch_predict_day = true;
        else if (key == "--simultaneous-day-update") { p.batch_predict_day = true; p.simultaneous_day_update = true; }
        else if (key == "--joint-debut") p.joint_debut = true;
        else if (key == "--day-debut") p.day_debut = true;
        else if (key == "--fit-temperatures") p.fit_temperatures = true;
        else throw std::runtime_error("unknown option " + key);
    }
    return p;
}

int main(int argc, char** argv) {
    try {
        std::string input;
        Parameters parameters = parse_parameters(argc, argv, input);
        parameters.track_records = !parameters.output.empty();
        int team_count = 0;
        auto matches = read_matches(input, team_count);
        double requested_friendly_temperature = parameters.friendly_temperature;
        double requested_competitive_temperature = parameters.competitive_temperature;
        if (parameters.fit_temperatures) {
            parameters.friendly_temperature = 1.0;
            parameters.competitive_temperature = 1.0;
        }
        NetworkModel model(team_count, parameters);
        std::ofstream output;
        if (!parameters.output.empty()) {
            output.open(parameters.output);
            output << "id\tday\tyear\tpw\tpd\tpl\texpected\tdifference\tvariance\tlatent_a\tlatent_b\tvar_a\tvar_b\tgames_a\tgames_b\tbaseline\tadjusted_mean_a\tadjusted_mean_b\tse_a\tse_b\teffective_a\teffective_b\treliability_a\treliability_b\n";
            output << std::setprecision(17);
        }
        std::vector<std::pair<int, double>> margin_window;
        std::size_t margin_start = 0;
        double margin_sum = 0.0;
        double logloss = 0.0, brier = 0.0, rps = 0.0;
        std::int64_t correct = 0, scored = 0;
        struct Stored { int year, day, outcome; bool friendly; std::array<double, 3> p; };
        std::vector<Stored> stored;
        if (parameters.fit_temperatures) stored.reserve(matches.size());
        auto started = std::chrono::steady_clock::now();

        for (std::size_t start = 0; start < matches.size();) {
            std::size_t end = start + 1;
            while (end < matches.size() && matches[end].day == matches[start].day) ++end;
            int year = matches[start].year;
            while (margin_start < margin_window.size() && margin_window[margin_start].first < year - 20) {
                margin_sum -= margin_window[margin_start].second;
                ++margin_start;
            }
            double environment = (20.0 * 1.10 + margin_sum) / (20.0 + double(margin_window.size() - margin_start));

            if (parameters.batch_predict_day) {
                if (parameters.day_debut) {
                    double value = model.debut_mean(year);
                    for (std::size_t k = start; k < end; ++k) {
                        if (!model.initialised(matches[k].a)) model.initialise_with(matches[k].a, matches[k].day, value);
                        if (!model.initialised(matches[k].b)) model.initialise_with(matches[k].b, matches[k].day, value);
                    }
                } else {
                    for (std::size_t k = start; k < end; ++k) model.initialise_pair(matches[k]);
                }
                std::unordered_set<int> participants;
                for (std::size_t k = start; k < end; ++k) { participants.insert(matches[k].a); participants.insert(matches[k].b); }
                for (int team : participants) { model.add_drift(team, matches[start].day); model.decay_breadth(team, matches[start].day); }
                std::vector<NetworkModel::Forecast> forecasts;
                forecasts.reserve(end - start);
                for (std::size_t k = start; k < end; ++k) forecasts.push_back(model.predict(matches[k]));
                for (std::size_t k = start; k < end; ++k) {
                    const auto& match = matches[k]; const auto& forecast = forecasts[k - start];
                    double baseline = model.reference(match.year, match.a, match.b);
                    auto record_a = model.record_values(match.a, baseline);
                    auto record_b = model.record_values(match.b, baseline);
                    if (parameters.fit_temperatures)
                        stored.push_back({match.year, match.day, match.outcome(), bool(match.friendly), forecast.p});
                    if (match.year >= parameters.score_first_year && match.day <= parameters.score_last_day) {
                        int outcome = match.outcome();
                        logloss -= std::log(std::max(1e-15, forecast.p[outcome]));
                        for (int c = 0; c < 3; ++c) brier += std::pow(forecast.p[c] - (c == outcome), 2);
                        double c1 = forecast.p[0] - (outcome == 0);
                        double c2 = forecast.p[0] + forecast.p[1] - (outcome <= 1);
                        rps += 0.5 * (c1 * c1 + c2 * c2);
                        correct += int(std::max_element(forecast.p.begin(), forecast.p.end()) - forecast.p.begin()) == outcome;
                        ++scored;
                    }
                    if (output) output << match.id << '\t' << match.day << '\t' << match.year << '\t'
                        << forecast.p[0] << '\t' << forecast.p[1] << '\t' << forecast.p[2] << '\t'
                        << forecast.expected << '\t' << forecast.difference << '\t' << forecast.variance << '\t'
                        << model.team_mean(match.a) << '\t' << model.team_mean(match.b) << '\t'
                        << model.team_variance(match.a) << '\t' << model.team_variance(match.b) << '\t'
                        << model.game_count(match.a) << '\t' << model.game_count(match.b) << '\t'
                        << baseline << '\t' << record_a[0] << '\t' << record_b[0] << '\t'
                        << record_a[1] << '\t' << record_b[1] << '\t' << record_a[2] << '\t' << record_b[2] << '\t'
                        << record_a[3] << '\t' << record_b[3] << '\n';
                    if (!parameters.simultaneous_day_update) model.update(match, environment);
                    if (match.margin() > 0) {
                        double excess = double(std::min(match.margin(), 7) - 1);
                        margin_window.push_back({match.year, excess}); margin_sum += excess;
                    }
                }
                if (parameters.simultaneous_day_update)
                    model.update_day_simultaneous(matches, start, end, environment);
            } else {
                for (std::size_t k = start; k < end; ++k) {
                    const auto& match = matches[k];
                    model.initialise_pair(match);
                    model.add_drift(match.a, match.day); model.add_drift(match.b, match.day);
                    model.decay_breadth(match.a, match.day); model.decay_breadth(match.b, match.day);
                    auto forecast = model.predict(match);
                    double baseline = model.reference(match.year, match.a, match.b);
                    auto record_a = model.record_values(match.a, baseline);
                    auto record_b = model.record_values(match.b, baseline);
                    if (parameters.fit_temperatures)
                        stored.push_back({match.year, match.day, match.outcome(), bool(match.friendly), forecast.p});
                    if (match.year >= parameters.score_first_year && match.day <= parameters.score_last_day) {
                        int outcome = match.outcome();
                        logloss -= std::log(std::max(1e-15, forecast.p[outcome]));
                        for (int c = 0; c < 3; ++c) brier += std::pow(forecast.p[c] - (c == outcome), 2);
                        double c1 = forecast.p[0] - (outcome == 0);
                        double c2 = forecast.p[0] + forecast.p[1] - (outcome <= 1);
                        rps += 0.5 * (c1 * c1 + c2 * c2);
                        correct += int(std::max_element(forecast.p.begin(), forecast.p.end()) - forecast.p.begin()) == outcome;
                        ++scored;
                    }
                    if (output) output << match.id << '\t' << match.day << '\t' << match.year << '\t'
                        << forecast.p[0] << '\t' << forecast.p[1] << '\t' << forecast.p[2] << '\t'
                        << forecast.expected << '\t' << forecast.difference << '\t' << forecast.variance << '\t'
                        << model.team_mean(match.a) << '\t' << model.team_mean(match.b) << '\t'
                        << model.team_variance(match.a) << '\t' << model.team_variance(match.b) << '\t'
                        << model.game_count(match.a) << '\t' << model.game_count(match.b) << '\t'
                        << baseline << '\t' << record_a[0] << '\t' << record_b[0] << '\t'
                        << record_a[1] << '\t' << record_b[1] << '\t' << record_a[2] << '\t' << record_b[2] << '\t'
                        << record_a[3] << '\t' << record_b[3] << '\n';
                    model.update(match, environment);
                    if (match.margin() > 0) {
                        double excess = double(std::min(match.margin(), 7) - 1);
                        margin_window.push_back({match.year, excess}); margin_sum += excess;
                    }
                    environment = (20.0 * 1.10 + margin_sum) / (20.0 + double(margin_window.size() - margin_start));
                }
            }
            start = end;
        }
        double fitted_friendly = requested_friendly_temperature;
        double fitted_competitive = requested_competitive_temperature;
        double fit_loss = std::numeric_limits<double>::quiet_NaN();
        if (parameters.fit_temperatures) {
            auto transformed = [](const std::array<double, 3>& p, double temperature) {
                std::array<double, 3> result{};
                double total = 0.0;
                for (int c = 0; c < 3; ++c) { result[c] = std::pow(std::max(1e-15, p[c]), temperature); total += result[c]; }
                for (double& value : result) value /= total;
                return result;
            };
            auto class_objective = [&](double temperature, bool friendly_class) {
                double loss = 0.0; std::int64_t count = 0;
                for (const auto& item : stored) {
                    if (item.friendly != friendly_class || item.year < parameters.fit_first_year || item.day > parameters.fit_last_day) continue;
                    auto p = transformed(item.p, temperature);
                    loss -= std::log(std::max(1e-15, p[item.outcome])); ++count;
                }
                return loss / count;
            };
            auto golden = [&](bool friendly_class) {
                double left = 0.50, right = 1.50;
                constexpr double ratio = 0.6180339887498948482;
                double c = right - ratio * (right - left), d = left + ratio * (right - left);
                double fc = class_objective(c, friendly_class), fd = class_objective(d, friendly_class);
                for (int iteration = 0; iteration < 80; ++iteration) {
                    if (fc < fd) { right = d; d = c; fd = fc; c = right - ratio * (right - left); fc = class_objective(c, friendly_class); }
                    else { left = c; c = d; fc = fd; d = left + ratio * (right - left); fd = class_objective(d, friendly_class); }
                }
                return 0.5 * (left + right);
            };
            fitted_friendly = golden(true);
            fitted_competitive = golden(false);
            logloss = brier = rps = 0.0; correct = scored = 0;
            double fit_sum = 0.0; std::int64_t fit_count = 0;
            for (const auto& item : stored) {
                double temperature = item.friendly ? fitted_friendly : fitted_competitive;
                auto p = transformed(item.p, temperature);
                if (item.year >= parameters.fit_first_year && item.day <= parameters.fit_last_day) {
                    fit_sum -= std::log(std::max(1e-15, p[item.outcome])); ++fit_count;
                }
                if (item.year < parameters.score_first_year || item.day > parameters.score_last_day) continue;
                logloss -= std::log(std::max(1e-15, p[item.outcome]));
                for (int c = 0; c < 3; ++c) brier += std::pow(p[c] - (c == item.outcome), 2);
                double c1 = p[0] - (item.outcome == 0);
                double c2 = p[0] + p[1] - (item.outcome <= 1);
                rps += 0.5 * (c1 * c1 + c2 * c2);
                correct += int(std::max_element(p.begin(), p.end()) - p.begin()) == item.outcome;
                ++scored;
            }
            fit_loss = fit_sum / fit_count;
        }
        double elapsed = std::chrono::duration<double>(std::chrono::steady_clock::now() - started).count();
        std::cout << std::setprecision(12)
                  << "{\"matches\":" << scored << ",\"log_loss\":" << logloss / scored
                  << ",\"brier\":" << brier / scored << ",\"rps\":" << rps / scored
                  << ",\"accuracy\":" << double(correct) / scored;
        if (parameters.fit_temperatures)
            std::cout << ",\"fit_log_loss\":" << fit_loss
                      << ",\"friendly_temperature\":" << fitted_friendly
                      << ",\"competitive_temperature\":" << fitted_competitive;
        std::cout << ",\"elapsed_seconds\":" << elapsed << "}\n";
    } catch (const std::exception& error) {
        std::cerr << error.what() << '\n';
        return 1;
    }
}
