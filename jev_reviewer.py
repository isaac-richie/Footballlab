"""Minimal native TypeSafe Jev reviewer; secret remains environment-only."""
import json
import os
import threading
import time
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

ENDPOINT = 'https://api.typesafe.ai/v1/systemone'
MODEL = 'jev-1.13.0'  # pin the version; do not silently change decision distributions
# Intentionally far below the provider's published ceiling.  This is a local
# process guard for interactive use and protects both quota and spend; it is not
# a replacement for a shared distributed limiter if this becomes multi-worker.
MAX_CALLS_PER_MINUTE = 60
MIN_SECONDS_BETWEEN_CALLS = .25
_lock = threading.Lock()
_calls = []
# Identical evidence gets the same answer: reuse it for a while instead of spending quota.
CACHE_SECONDS = 6 * 3600
_cache = {}


def _permit(now=None):
    now = time.monotonic() if now is None else now
    with _lock:
        while _calls and now - _calls[0] >= 60:
            _calls.pop(0)
        if len(_calls) >= MAX_CALLS_PER_MINUTE or (_calls and now - _calls[-1] < MIN_SECONDS_BETWEEN_CALLS):
            return False
        _calls.append(now)
        return True


def review(forecast):
    """Return typed Jev evidence. It is never permitted to alter policy gates."""
    key = os.environ.get('TYPESAFE_API_KEY', '').strip()
    if not key:
        return {'status': 'unavailable', 'reason': 'TYPESAFE_API_KEY is not present in the server environment.'}
    pricing = forecast.get('pricing') or {}
    latest = forecast.get('latest_result')
    state = {
        'model_version': forecast['model']['version'],
        'analysis_date': forecast['analysis_date'],
        'readiness_status': forecast['readiness']['status'],
        'readiness_issues': forecast['readiness']['issues'],
        'recent_team_samples': forecast['recent_team_samples'],
        'expected_goals': [round(x, 3) for x in forecast['expected_goals']],
        'one_x_two_probabilities': [round(x, 4) for x in forecast['probabilities']],
        'manual_market_present': bool(forecast.get('market')),
        'deterministic_action': forecast['decision']['action'],
        'pricing_source': pricing.get('source', 'model'),
        'pricing_fit_error': round(pricing['fit_error'], 4) if isinstance(pricing.get('fit_error'), (int, float)) else None,
        'fixture_date': pricing.get('fixture_date'),
        'latest_result_used': latest,
        'days_since_latest_result': (_days(forecast['analysis_date'], latest) if latest else None),
        'training_matches': forecast.get('sample_matches'),
    }
    cache_key = json.dumps(state, sort_keys=True)
    with _lock:
        hit = _cache.get(cache_key)
    if hit and time.monotonic() - hit[0] < CACHE_SECONDS:
        return dict(hit[1], cached=True)
    if not _permit():
        return {'status': 'throttled', 'reason': 'Local Jev circuit breaker: maximum 60 calls/minute and 4 calls/second per process.'}
    payload = {
        'model': MODEL,
        'state': json.dumps(state, sort_keys=True),
        'questions': {
            'needs_human_review': {
                'type': 'noul',
                'instructions': 'Does this forecast record contain a data-quality, freshness, pricing-fit, or missing-evidence reason that requires human review before relying on it? A long gap since the latest result is only a concern if fixtures were expected in between.'
            },
            'evidence_state': {
                'type': 'choice',
                'instructions': 'Classify the evidence available for this research forecast. Do not infer facts not present in the record.',
                'criteria': {
                    'sufficient_for_research_review': 'The record is research_only with no stated quality issue and contains the inputs needed for a bounded research review.',
                    'insufficient_or_needs_review': 'The record is review_required, has a stated quality issue, or lacks inputs needed for a bounded research review.'
                }
            }
        }
    }
    request = Request(ENDPOINT, data=json.dumps(payload).encode(), headers={
        'Authorization': 'Bearer ' + key, 'Content-Type': 'application/json'
    })
    try:
        with urlopen(request, timeout=12) as response:
            response_body = json.load(response)
    except (HTTPError, URLError, TimeoutError, ValueError) as exc:
        return {'status': 'unavailable', 'reason': 'Jev request failed: ' + str(exc)}
    answers = response_body.get('answers')
    if not isinstance(answers, dict):
        return {'status': 'unavailable', 'reason': 'Jev response did not contain typed answers.'}
    result = {'status': 'available', 'provider': 'TypeSafe Jev', 'model': response_body.get('model', MODEL),
              'answers': answers, 'usage': response_body.get('usage', {}), 'cached': False,
              'authority': 'Advisory only. Deterministic quality gates and research policy remain authoritative.'}
    with _lock:
        _cache[cache_key] = (time.monotonic(), result)
        if len(_cache) > 500:
            _cache.pop(next(iter(_cache)))
    return result


def _days(a, b):
    import datetime as dt
    return (dt.date.fromisoformat(a) - dt.date.fromisoformat(b)).days
