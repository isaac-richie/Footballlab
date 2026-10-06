# Beat the Lab: community prediction league

A free, public football prediction game. Players split 100% between home, draw and away for upcoming matches. Picks lock at kickoff and stay hidden until then. After the match each pick is scored against the Lab's model forecast. No money is involved.

```
community/
  supabase/schema.sql     tables, row-level security, scoring views (run once in Supabase)
  supabase/test_*.sql     local rule tests (run_tests.sh)
  web/                    static site: index.html, app.js, data.js, styles.css, config.js
  sync.py                 pushes fixtures, results and Lab forecasts from Football Lab
```

## Try it now (demo mode)

```sh
python3 -m http.server 8790 --directory community/web
```

Open http://localhost:8790. With `config.js` blank the site runs on sample data; sign in with any email and the code `123456`.

## Spot Kick (web game)

`web/game/` is a penalty shootout that deploys with the league site at `/game/`. Best of five then sudden death against the computer: aim and hold to power your kick, then go in goal and read the taker's run-up (it leans toward the real side 60% of the time). The **Daily Shootout** uses a date seed so everyone faces the same keeper and takers that day; the first result of the day is what you share, as a WhatsApp-ready ⚽/❌ row. No images, libraries or network calls; sound is synthesised in the browser and can be muted.

Rules and balance live in `web/game/engine.js` and are tested with `node --test community/web/game/engine.test.js` (also run in CI). Tuned by simulation: a well-placed shot scores about 74% (real penalties are about 75%), a weak one about 53%; as keeper a random dive saves about 20%, reading the tell about 40%, and standing still about 11%.

## Scoring

For each finished match the Brier score is the sum of squared errors over home, draw and away (0 is perfect, 2 is the worst). Points are `(Lab's Brier − your Brier) × 100`. Beating the Lab scores positive points; trailing it scores negative. Brier is a proper scoring rule: over many matches you maximize expected points by entering your honest probabilities, so going all-in on a hunch is punished when it misses. When a fixture has no Lab forecast, the benchmark is one third each.

Badges: **Upset caller** (50%+ on a result the Lab gave under 25%), **Bang on** (80%+ on the actual result), **Sharp week** (positive points over a round of 5+ picks). Streaks count consecutive weeks played. Crowd consensus is computed only from locked picks.

## Fairness and security

All enforced in the database, not the browser:

- Players can write only their own picks, only before the fixture locks (exact kickoff when known, otherwise 00:00 UTC on match day).
- Nobody, including anonymous visitors, can read another player's pick until it locks. Before then only a count is shown.
- Fixtures and results are written only with the service key, which never leaves your machine.
- The Lab forecast is frozen at lock by a trigger, so it can never be recomputed with knowledge of the result.
- Private leagues are visible only to members; joining needs the invite code.

`supabase/run_tests.sh` checks each of these against a local Postgres.

## Go live

1. Create a free project at https://supabase.com. In **SQL Editor**, paste `supabase/schema.sql` and run it.
2. **Authentication → Providers → Email**: keep Email enabled. In **Email Templates → Magic Link**, include `{{ .Token }}` so players receive a 6-digit code. Set **URL Configuration → Site URL** to your site address.
3. For a public site, turn on **Authentication → Bot and Abuse Protection** (CAPTCHA) and review rate limits. CAPTCHA needs a small addition to the sign-in form; ask before enabling.
4. From **Project Settings → API**, put the Project URL and the `anon` public key in `web/config.js`. Put the URL and the `service_role` key in Football Lab's `.env` as `SUPABASE_URL` and `SUPABASE_SERVICE_ROLE_KEY`. Never put the service key in `web/`.
5. Sync, then schedule it daily (cron, launchd or a CI job):
   ```sh
   python3 app.py refresh && python3 community/sync.py
   ```
   `python3 community/sync.py --dry-run` shows what would be sent.
6. Deploy `community/web` as a static site, for example `npx vercel deploy community/web --prod`, or connect a Git repository with root directory `community/web`. `vercel.json` adds security headers.

## Before launch: legal and community checklist

- **Privacy:** sign-in stores email addresses with Supabase. Publish a privacy notice and a way to delete an account (deleting the user in Supabase removes their profile and picks).
- **Terms:** free to play, no prizes or stakes, 18+. If you ever add prizes, check local promotion and gaming law first.
- **Data licences:** OpenFootball is CC0. 2. Bundesliga fixtures come from OpenLigaDB under ODbL: keep the attribution, and if you republish the fixture database itself it must stay under ODbL. Bookmaker odds are never published: football-data.co.uk reuse terms are unverified, and scraped bookmaker data must not be redistributed.
- **Moderation:** usernames are the only user-generated text. Remove abusive ones by editing or deleting the profile in Supabase. Consider a blocklist before a big launch.
- **Kickoff times:** without an exact time, picks lock at 00:00 UTC on match day. That is conservative but early for evening kickoffs; exact times arrive automatically for fixtures in the live-odds cache.
