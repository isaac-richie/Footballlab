"""Typed, deterministic research-decision policy.

This is deliberately not branded as Jev: Jev is an external decision API and
is not configured in this local project. The shape follows typed-decision
design—bounded actions, explicit evidence and conservative defaults—while all
policy remains inspectable in code.
"""

POLICY = {
    'version': 'research-policy-1.0',
    'allowed_actions': ['withhold', 'research_candidate'],
    'minimum_expected_return': .03,
    'minimum_probability_gap': .04,
    'minimum_model_probability': .40,
    'rule': 'No action is a wagering recommendation. Missing or review-required evidence always withholds.',
}


def assess(forecast):
    """Return a bounded decision with a fully inspectable evidence trace."""
    quality = forecast['readiness']
    trace = [dict(check='data_quality', passed=quality['status'] == 'research_only',
                  observed=quality['status'], required='research_only')]
    if quality['status'] != 'research_only':
        return dict(action='withhold', policy=POLICY, trace=trace,
                    reasons=['The data for this match needs checking first, so we are not comparing prices.'])
    market = forecast.get('market')
    if not market:
        trace.append(dict(check='complete_market_odds', passed=False, observed='missing', required='three decimal 1X2 odds'))
        return dict(action='withhold', policy=POLICY, trace=trace,
                    reasons=['Add the bookie odds to see if any price is worth a look.'])
    candidates = []
    for index, label in enumerate(('home', 'draw', 'away')):
        probability, gap = forecast.get('model_view', forecast)['probabilities'][index], market['gap'][index]
        expected_return = market['expected_return'][index]
        passes = (expected_return >= POLICY['minimum_expected_return'] and gap >= POLICY['minimum_probability_gap'] and
                  probability >= POLICY['minimum_model_probability'])
        trace.append(dict(check='market_'+label, passed=passes, probability=probability,
                          probability_gap=gap, expected_return=expected_return,
                          required=dict(minimum_probability=POLICY['minimum_model_probability'],
                                        minimum_probability_gap=POLICY['minimum_probability_gap'],
                                        minimum_expected_return=POLICY['minimum_expected_return'])))
        if passes:
            candidates.append(dict(outcome=label, probability=probability, gap=gap,
                                   expected_return=expected_return, fair_odds=1/probability))
    if not candidates:
        return dict(action='withhold', policy=POLICY, trace=trace,
                    reasons=['No price here is clearly better than it should be.'])
    return dict(action='research_candidate', policy=POLICY, trace=trace, candidates=candidates,
                reasons=['One price looks generous by our numbers. Treat it as an idea to check, not a tip.'])
