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

## Kickabout (multiplayer football)

`web/match/` is a light top-down football game: 3v3, 5v5 or 11v11, 3 or 5 minutes, against the computer or a friend. Move with WASD, arrows, a touch joystick or a game controller; pass, hold to shoot, tackle and switch player. The pitch is a cage (the ball rebounds off the boards), so there are no throw-ins. On a phone held upright the pitch turns vertical, and the guest's view is rotated so everyone attacks the same way on screen.

**How online play works (zero cost per match).** The host's browser runs the match (`engine.js`, 60 steps a second) and sends the state 20 times a second; the guest sends button presses. Actions travel as counters, so a dropped or repeated packet never loses or doubles a pass or shot. The two browsers find each other through a short handshake (`net.js`): over Supabase Realtime once configured, or over a same-device channel for testing. After that, game traffic goes directly between the players over WebRTC, so it does not count against Supabase's free-plan limit of 100 messages a second per project. If a direct link cannot form (some strict networks), it falls back to relaying through the handshake channel at 10 updates a second. A relay (TURN) server would fix those cases but costs money, so it is not included.

Limits of this draft: no prediction on the guest side, so the guest sees their own movement about one network round trip late; the host's match keeps running if they switch tabs, but background tabs update slowly. Match chat has a basic word filter and a rate limit only; open public chat needs proper moderation first (see the social plan).

Tests: `node --test community/web/match/engine.test.js` (also run in CI).

## Terrace (social, 18+)

`web/social/` is the community hub: public rooms (General, one per league, Kickabout, Spot Kick), direct messages between mutual friends, friend requests, and challenges that drop two friends into a Kickabout room. It runs on Supabase with `supabase/social.sql` (run it after `schema.sql`), and in demo mode with sample players until configured.

The whole platform is **18+**: a profile cannot exist without the player confirming their age (`profiles.adult`), and every social action requires a profile. Safety rules are enforced in the database and covered by `supabase/test_social.sql`:

- Direct messages only between mutual friends; outsiders can't read or post in them.
- Blocking either way cuts all contact: ends the friendship and pending requests, stops DMs and new requests, and hides each person's messages from the other.
- Reports go to moderators; three distinct reports hide a message automatically until reviewed.
- A server-side word filter and a rate limit of 5 messages per 10 seconds; 3 challenges a minute.
- Banned players can neither read nor post. Signed-out visitors see nothing social.
- No image uploads in v1.

**Moderation.** Appoint a moderator in the Supabase SQL editor: `insert into public.moderators values ('<user uuid>');`. Moderators see hidden messages (marked) with Hide/Unhide on every message, see all reports (`select * from reports where status = 'open'`), and can suspend with `select ban_user('<user uuid>', 72, 'reason');`. Before opening to the public: publish community rules and a privacy notice, name who handles reports and how fast, and plan for law-enforcement requests and reports of under-18 users (the `underage` report reason exists for this).

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
