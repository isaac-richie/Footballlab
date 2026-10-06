"""Reproducible all-league retrospective evaluation artifact."""
import datetime as dt
import json
from app import ROOT, LEAGUES, MODEL, backtest, load
from quality import atomic_write, digest


if __name__ == '__main__':
    data = load()
    report = dict(generated_at=dt.datetime.now(dt.timezone.utc).isoformat(),
                  data_hash=digest(data), model=MODEL, leagues={}, failures={})
    atomic_write(ROOT/'reports'/'datasets'/f'{report["data_hash"]}.json', json.dumps(data,indent=2))
    report['code_hash'] = digest({name:(ROOT/name).read_text() for name in ['app.py','quality.py','evaluation.py','validate.py']})
    atomic_write(ROOT/'reports'/'code'/f'{report["code_hash"]}.json', json.dumps({name:(ROOT/name).read_text() for name in ['app.py','quality.py','evaluation.py','validate.py']},indent=2))
    for league in LEAGUES:
        try:
            report['leagues'][league] = backtest(data, league)
            result = report['leagues'][league]
            print(league, result['matches'], 'Dixon-Coles', result['model']['log_loss'],
                  'Poisson', result['poisson_no_correction']['log_loss'], flush=True)
        except ValueError as exc:
            report['failures'][league] = str(exc)
            print(league, str(exc), flush=True)
    atomic_write(ROOT/'reports'/'validation.json', json.dumps(report,indent=2))
