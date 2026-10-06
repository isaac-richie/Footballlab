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
    if not _permit():
        return {'status': 'throttled', 'reason': 'Local Jev circuit breaker: maximum 60 calls/minute and 4 calls/second per process.'}
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
    }
    payload = {
        'model': MODEL,
        'state': json.dumps(state, sort_keys=True),
        'questions': {
            'needs_human_review': {
                'type': 'noul',
                'instructions': 'Does this forecast record contain a data-quality, freshness, or missing-evidence reason that requires human review before relying on it?'
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
    return {'status': 'available', 'provider': 'TypeSafe Jev', 'model': response_body.get('model', MODEL),
            'answers': answers, 'usage': response_body.get('usage', {}),
            'authority': 'Advisory only. Deterministic quality gates and research policy remain authoritative.'}
