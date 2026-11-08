import datetime as dt
import json
import unittest

import app

TODAY = dt.date(2026, 11, 8)
TEAMS = [('Arsenal FC', 'FC Arsenal'), ('Aston Villa FC', 'Aston Villa'), ('Chelsea FC', 'Chelsea FC'), ('Everton FC', 'Everton FC')]


def ours(date, home, away, goals=None):
    return dict(league_id='en.1', league='England — Premier League', season='2026-27', date=date, home=home, away=away, goals=goals, ht=None)


def theirs(date, home, away, goals=None, kickoff=None):
    results = [] if goals is None else [dict(resultTypeKind='After90Minutes', resultOrderID=2, pointsTeam1=goals[0], pointsTeam2=goals[1])]
    stamp = kickoff or f'{date}T15:00:00Z'
    return dict(matchDateTime=stamp[:19], matchDateTimeUTC=stamp, team1=dict(teamName=home), team2=dict(teamName=away), matchResults=results)


def fixture_set(n_agreeing, disagree=0):
    """Both sources score the same early games; the open feed lacks the later ones."""
    o, t = [], []
    names = dict(TEAMS)
    pairs = [(h, a) for h, _ in TEAMS for a, _ in TEAMS if h != a]
    for i, (h, a) in enumerate(pairs[:n_agreeing + disagree]):
        date = (TODAY - dt.timedelta(days=60 - i)).isoformat()
        o.append(ours(date, h, a, [1, 0]))
        t.append(theirs(date, names[h], names[a], [1, 0] if i < n_agreeing else [0, 0]))
    return o, t, names, pairs[n_agreeing + disagree:]


class PatchTest(unittest.TestCase):
    def run_patch(self, matches, feed, trusted=False, **kw):
        return app.patch_openligadb(matches, {}, 'en.1', 'pl', trusted, raw=json.dumps(feed).encode(), today=TODAY, **kw)

    def test_corrects_date_and_kickoff_of_unplayed_game(self):
        o, t, names, rest = fixture_set(2)
        h, a = rest[0]
        o.append(ours('2026-11-07', h, a))
        t.append(theirs('2026-11-08', names[h], names[a], kickoff='2026-11-08T16:30:00Z'))
        report = self.run_patch(o, t)
        self.assertEqual((o[-1]['date'], o[-1]['kickoff']), ('2026-11-08', '2026-11-08T16:30:00Z'))
        self.assertEqual(report['dates'], 1)

    def test_fills_scores_only_when_the_feed_agrees(self):
        o, t, names, rest = fixture_set(4)
        h, a = rest[0]
        o.append(ours('2026-11-01', h, a)); t.append(theirs('2026-11-01', names[h], names[a], [2, 1]))
        self.run_patch(o, t, min_overlap=4)
        self.assertEqual((o[-1]['goals'], o[-1]['goals_source']), ([2, 1], 'openligadb'))

    def test_disagreeing_feed_corrects_dates_but_fills_no_scores(self):
        o, t, names, rest = fixture_set(3, disagree=1)                  # 75% agreement
        h, a = rest[0]
        o.append(ours('2026-11-01', h, a)); t.append(theirs('2026-11-02', names[h], names[a], [2, 1]))
        report = self.run_patch(o, t, min_overlap=4)
        self.assertIsNone(o[-1]['goals'])
        self.assertEqual(o[-1]['date'], '2026-11-02')
        self.assertFalse(report['scores_trusted'])

    def test_trusted_feed_fills_without_overlap(self):
        o, t, names, rest = fixture_set(0)
        o += [ours('2026-11-01', h, a) for h, a in rest]
        t += [theirs('2026-11-01', names[h], names[a], [1, 1]) for h, a in rest]
        self.run_patch(o, t, trusted=True)
        self.assertTrue(all(m['goals'] == [1, 1] for m in o))

    def test_never_overwrites_an_existing_score(self):
        o, t, names, _ = fixture_set(4, disagree=1)
        self.run_patch(o, t, min_overlap=1, min_agree=0)
        self.assertEqual(o[-1]['goals'], [1, 0])

    def test_unpaired_team_changes_nothing(self):
        o, t, names, rest = fixture_set(2)
        h, a = rest[0]
        o.append(ours('2026-11-07', h, a))
        t.append(theirs('2026-11-08', 'Real Madrid', names[a]))
        with self.assertRaises(ValueError):
            self.run_patch(o, t)
        self.assertEqual(o[-1]['date'], '2026-11-07')


if __name__ == '__main__':
    unittest.main()
