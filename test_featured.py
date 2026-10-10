import unittest

from featured import anticipation, write_up


def fx(p, over=0.55, btts=0.55, source='model', mp=None):
    return dict(home='Home FC', away='Away FC', probabilities=p, over25=over, btts=btts,
                top_score=dict(score='1–1', probability=0.12), source=source, model_probabilities=mp)


class FeaturedTests(unittest.TestCase):
    def test_big_close_games_rank_highest(self):
        big_close = anticipation(2.3, 2.2, [0.37, 0.26, 0.37])
        big_lopsided = anticipation(2.3, 2.2, [0.75, 0.15, 0.10])
        small_close = anticipation(0.9, 0.8, [0.37, 0.26, 0.37])
        self.assertGreater(big_close, big_lopsided)
        self.assertGreater(big_close, small_close)

    def test_write_up_says_only_what_numbers_support(self):
        close = ' '.join(write_up(fx([0.36, 0.27, 0.37]), 1.5, 1.5))
        self.assertIn('Too close to call', close)
        fav = ' '.join(write_up(fx([0.15, 0.2, 0.65], over=0.7, btts=0.6), 1.0, 2.2))
        self.assertIn('Away FC are clear favourites at 65% away from home', fav)
        self.assertIn('over 2.5 at 70%', fav)
        self.assertIn('Form check', fav)
        tight = ' '.join(write_up(fx([0.4, 0.33, 0.27], over=0.38), 1.5, 1.5))
        self.assertIn('under 2.5 goals at 62%', tight)
        disagree = ' '.join(write_up(fx([0.5, 0.3, 0.2], source='live', mp=[0.62, 0.25, 0.13]), 1.5, 1.5))
        self.assertIn('Our model rates Home FC higher than the bookies', disagree)
        self.assertNotIn('Our model', ' '.join(write_up(fx([0.5, 0.3, 0.2], mp=[0.62, 0.25, 0.13]), 1.5, 1.5)))


if __name__ == '__main__':
    unittest.main()
