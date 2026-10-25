"""Chronological evaluation; diagnostics do not fit or calibrate the model."""
import datetime as dt
import math
import random
from collections import defaultdict


def metrics(records, key='probabilities'):
    if not records:
        raise ValueError('No eligible evaluation matches')
    return dict(log_loss=sum(-math.log(max(r[key][r['outcome']], 1e-12)) for r in records)/len(records),
                brier=sum(sum((p-int(i == r['outcome']))**2 for i,p in enumerate(r[key])) for r in records)/len(records),
                accuracy=sum(max(range(3), key=lambda i:r[key][i]) == r['outcome'] for r in records)/len(records))


def calibration(records):
    tables = {}
    for k, name in enumerate(('home', 'draw', 'away')):
        bins = []
        for bucket in range(10):
            group = [r for r in records if min(9, int(r['probabilities'][k]*10)) == bucket]
            if not group:
                continue
            n = len(group)
            observed = sum(r['outcome'] == k for r in group)/n
            mean = sum(r['probabilities'][k] for r in group)/n
            z = 1.96
            center = (observed+z*z/(2*n))/(1+z*z/n)
            half = z*math.sqrt(observed*(1-observed)/n+z*z/(4*n*n))/(1+z*z/n)
            bins.append(dict(lower=bucket/10, upper=(bucket+1)/10, matches=n, predicted=mean,
                             observed=observed, observed_interval_95=[center-half, center+half]))
        tables[name] = bins
    return tables


def comparison_interval(records):
    # Resample whole match dates; this preserves dependence among same-day games.
    groups = defaultdict(list)
    for r in records:
        delta = -math.log(max(r['probabilities'][r['outcome']],1e-12)) + math.log(max(r['baseline'][r['outcome']],1e-12))
        groups[r['date']].append(delta)
    blocks = list(groups.values())
    rng = random.Random(2718)
    samples = []
    for _ in range(500):
        sample = [x for _ in blocks for x in rng.choice(blocks)]
        samples.append(sum(sample)/len(sample))
    samples.sort()
    return dict(mean_delta=sum(x for block in blocks for x in block)/len(records),
                interval_95=[samples[12], samples[487]], bootstrap_replicates=500,
                method='Paired date-block bootstrap, seed 2718; negative favors model. Does not capture all temporal/team dependence.')


def temperature_scale(probabilities, temperature):
    logits = [math.log(max(p, 1e-12)) / temperature for p in probabilities]
    peak = max(logits)
    weights = [math.exp(value - peak) for value in logits]
    total = sum(weights)
    return [value / total for value in weights]


def fit_temperature(records):
    """Fit one multiclass temperature on prior, prequential predictions only."""
    if len(records) < 100:
        raise ValueError('At least 100 calibration predictions are required')

    def objective(temperature):
        return sum(-math.log(max(temperature_scale(row['probabilities'], temperature)[row['outcome']], 1e-12))
                   for row in records) / len(records)

    # Golden-section search is deterministic, bounded and needs no dependencies.
    low, high = .5, 2.5
    ratio = (math.sqrt(5) - 1) / 2
    left, right = high - ratio * (high - low), low + ratio * (high - low)
    left_score, right_score = objective(left), objective(right)
    for _ in range(80):
        if left_score <= right_score:
            high, right, right_score = right, left, left_score
            left = high - ratio * (high - low)
            left_score = objective(left)
        else:
            low, left, left_score = left, right, right_score
            right = low + ratio * (high - low)
            right_score = objective(right)
    return (low + high) / 2


def paired_date_interval(records, calibrated, replicates=1000):
    """Paired date-block interval for calibrated minus raw test log loss."""
    grouped = defaultdict(list)
    for row, adjusted in zip(records, calibrated):
        outcome = row['outcome']
        delta = (-math.log(max(adjusted[outcome], 1e-12))
                 + math.log(max(row['probabilities'][outcome], 1e-12)))
        grouped[row['date']].append(delta)
    blocks = list(grouped.values())
    rng = random.Random(9417)
    samples = []
    for _ in range(replicates):
        sampled = [rng.choice(blocks) for _ in blocks]
        samples.append(sum(value for block in sampled for value in block)
                       / sum(len(block) for block in sampled))
    samples.sort()
    return dict(mean_delta=sum(value for block in blocks for value in block)
                / sum(len(block) for block in blocks),
                interval_95=[samples[int(.025 * replicates)], samples[int(.975 * replicates) - 1]],
                bootstrap_replicates=replicates,
                method='Paired match-date bootstrap; negative favors calibrated probabilities.')


def evaluate(data, league_id):
    from app import LEAGUES, MODEL, distribution, history
    import market_ratings
    from quality import digest
    if league_id not in LEAGUES:
        raise ValueError('Choose a supported league.')
    today = dt.date.today()
    rows = history(data, today.isoformat(), league_id)
    all_rows = [m for m in data['matches'] if m['league_id'] == league_id]
    seasons = sorted({m['season'] for m in rows})
    eligible = []
    for season in seasons:
        end_year = int(season[:4])+1
        scheduled = [m for m in all_rows if m['season'] == season]
        completed = [m for m in rows if m['season'] == season]
        if dt.date(end_year,7,1) < today and len(completed) >= 200 and len(completed)/len(scheduled) >= .9:
            if sum(m['date'] < min(x['date'] for x in completed) for m in rows) >= 300:
                eligible.append(season)
    selected = eligible[-3:]
    records = []
    # Refit once per date, then score every game on that date.  This both
    # prevents same-day leakage and makes the evaluated model identical to the
    # forecast endpoint without needlessly fitting it once per fixture.
    by_date = defaultdict(list)
    for match in rows:
        if match['season'] in selected:
            by_date[match['date']].append(match)
    state = None
    for date, matches in sorted(by_date.items()):
        prior = [m for m in rows if m['date'] < date]
        if len(prior) < 100:
            continue
        # The production fit, so this backtest scores exactly what the forecasts use.
        expected, rho, fit = market_ratings.fit(prior, date, sorted({t for m in matches for t in (m['home'], m['away'])}),
                                                start=state)
        state = expected.state       # the next date's fit starts here; same converged answer, far fewer steps
        base = [1.,1.,1.]
        for m in prior:
            h,a = m['goals']
            base[0 if h>a else 1 if h==a else 2] += 1
        goal_baselines = {str(line): (1+sum(sum(m['goals']) > line for m in prior))/(len(prior)+2)
                          for line in map(float, distribution(1., 1.)['total_goal_overs'])}
        btts_baseline = (1+sum(m['goals'][0]>0 and m['goals'][1]>0 for m in prior))/(len(prior)+2)
        for match in matches:
            lh, la = expected(match['home'], match['away'])
            forecast = distribution(lh, la, rho, fit['calibration'])
            h,a = match['goals']
            record = dict(date=match['date'], season=match['season'], home=match['home'], away=match['away'],
                          probabilities=forecast['probabilities'],
                          poisson_probabilities=distribution(lh, la, 0)['probabilities'],
                          baseline=[p/sum(base) for p in base],
                          outcome=0 if h>a else 1 if h==a else 2,
                          goal_markets={})
            for line, p in forecast['total_goal_overs'].items():
                observed = int(h+a > float(line))
                empirical = goal_baselines[str(float(line))]
                record['goal_markets']['over_'+line] = dict(p=p, actual=observed, baseline=empirical)
            actual_btts = int(h>0 and a>0)
            record['goal_markets']['btts'] = dict(p=forecast['btts'], actual=actual_btts,
                baseline=btts_baseline)
            records.append(record)
    if not records:
        raise ValueError('No completed evaluation season with 300 earlier training matches')
    goal_scores = {}
    for name in records[0]['goal_markets']:
        goal_scores[name] = {k:sum((r['goal_markets'][name][field]-r['goal_markets'][name]['actual'])**2 for r in records)/len(records)
                            for k,field in [('brier','p'),('baseline_brier','baseline')]}
    poisson_scores = metrics(records, 'poisson_probabilities')
    ablation = [dict(season=s, matches=sum(r['season'] == s for r in records),
                     dixon_coles=metrics([r for r in records if r['season'] == s]),
                     poisson=metrics([r for r in records if r['season'] == s], 'poisson_probabilities'))
                for s in selected]
    temporal_calibration = None
    if len(selected) >= 3:
        calibration_records = [r for r in records if r['season'] in selected[:-1]]
        heldout_records = [r for r in records if r['season'] == selected[-1]]
        if len(calibration_records) >= 100 and len(heldout_records) >= 100:
            temperature = fit_temperature(calibration_records)
            adjusted = [temperature_scale(r['probabilities'], temperature) for r in heldout_records]
            adjusted_records = [dict(r, probabilities=p) for r, p in zip(heldout_records, adjusted)]
            temporal_calibration = dict(
                method='One global multiclass temperature fitted on the first two selected seasons; evaluated once on the latest season.',
                calibration_seasons=selected[:-1], heldout_season=selected[-1],
                calibration_matches=len(calibration_records), heldout_matches=len(heldout_records),
                temperature=temperature,
                raw=metrics(heldout_records), calibrated=metrics(adjusted_records),
                log_loss_delta_interval=paired_date_interval(heldout_records, adjusted))
    return dict(league=LEAGUES[league_id], model_spec=MODEL, data_hash=digest(data['matches']),
                season=', '.join(selected), matches=len(records), model=metrics(records),
                poisson_no_correction=poisson_scores, dixon_coles_ablation=ablation,
                league_baseline=metrics(records,'baseline'),
                by_season=[dict(season=s, matches=sum(r['season']==s for r in records),
                    model=metrics([r for r in records if r['season']==s]),
                    baseline=metrics([r for r in records if r['season']==s],'baseline')) for s in selected],
                calibration=calibration(records), log_loss_comparison=comparison_interval(records),
                temporal_calibration=temporal_calibration,
                goal_market_scores=goal_scores, predictions=records,
                method='Up to three completed seasons; expanding history, all same-day games excluded. The same pre-specified regularized Poisson model used by the forecast endpoint is refit once per match date. No tuning on these results. Retrospective source corrections remain a limitation. Lower log loss/Brier is better. Calibration bins are diagnostics, not fitted calibration. No bookmaker-profit claim.')
