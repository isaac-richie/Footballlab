import datetime as dt
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError
import app
from quality import coverage, normalize
from evaluation import calibration, metrics


class QualityTests(unittest.TestCase):
    def test_invalid_score_is_not_silently_a_future_fixture(self):
        raw = json.dumps({'matches':[dict(date='2025-01-01',team1='A',team2='B',score=[-1,2])]})
        with self.assertRaises(ValueError):
            normalize(raw,'en.1','League','2024-25')

    def test_refresh_updates_known_partition_and_preserves_failed_partition(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder); data_path=root/'data.json'
            old=dict(matches=[dict(date='2025-01-01',home='A',away='B',goals=None,league_id='en.1',season='2024-25'),
                              dict(date='2024-01-01',home='A',away='B',goals=[1,0],league_id='en.1',season='2023-24')],
                     sources=[dict(url=app.SOURCE+'2024-25/en.1.json')])
            data_path.write_text(json.dumps(old))
            raw=json.dumps({'matches':[dict(date='2025-01-02',team1='A',team2='B',score={'ft':[2,1]})]}).encode()
            def fetch(url, **kwargs):
                if url.endswith('2024-25/en.1.json'):return io.BytesIO(raw)
                raise HTTPError(url,404,'Missing',None,None)
            with patch.object(app,'ROOT',root),patch.object(app,'DATA',data_path),patch.object(app,'urlopen',fetch),patch('builtins.print'):
                app.refresh()
            actual=json.loads(data_path.read_text())
            self.assertEqual(len(actual['matches']),2)
            self.assertTrue(any(m['goals']==[2,1] for m in actual['matches']))
            self.assertFalse(any(m['date']=='2025-01-01' for m in actual['matches']))
            self.assertTrue(any(m['season']=='2023-24' for m in actual['matches']))
            self.assertIn('checked_at',actual['sources'][0])

    def test_total_refresh_failure_preserves_file_bytes(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'data.json'
            raw=json.dumps(dict(matches=[],sources=[]));path.write_text(raw)
            with patch.object(app,'DATA',path),patch.object(app,'urlopen',side_effect=HTTPError('x',404,'Missing',None,None)):
                with self.assertRaises(RuntimeError):app.refresh()
            self.assertEqual(path.read_text(),raw)

    def test_league_isolation(self):
        rows=[dict(date='2025-01-01',home='A',away='B',goals=[2,1],league_id='en.1') for _ in range(100)]
        request=dict(home='A',away='B',date='2025-02-01',league_id='en.1')
        for row in rows:row['season']='2024-25'
        original=app.predict(dict(matches=rows),request)['probabilities']
        rows.extend(dict(date='2025-01-01',home='A',away='B',goals=[9,0],league_id='de.1') for _ in range(100))
        self.assertEqual(original,app.predict(dict(matches=rows),request)['probabilities'])

    def test_quality_gate_detects_unverified_source(self):
        check=coverage(dict(matches=[]), 'en.1',dt.date.today().isoformat())
        self.assertEqual(check['status'],'review_required')
        self.assertIn('Current source freshness unverified',check['issues'])

    def test_probability_invariants_and_rate_validation(self):
        for lh,la in [(0.05,6),(6,.05),(6,6),(1.5,1.2)]:
            r=app.distribution(lh,la)
            self.assertAlmostEqual(sum(r['probabilities']),1)
            values=list(r['total_goal_overs'].values())
            self.assertEqual(values,sorted(values,reverse=True))
            self.assertLessEqual(r['win_to_nil']['home'],r['clean_sheets']['home'])
        with self.assertRaises(ValueError):app.distribution(float('nan'),1)

    def test_perfect_calibration_known_sample(self):
        rows=[dict(probabilities=[.5,.5,0],outcome=i%2) for i in range(20)]
        self.assertAlmostEqual(metrics(rows)['log_loss'],__import__('math').log(2))
        self.assertEqual(calibration(rows)['home'][0]['observed'],.5)


if __name__=='__main__':unittest.main()
