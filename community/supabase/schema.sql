-- Beat the Lab: public football prediction league.
-- Run once in the Supabase SQL editor (or psql) on a new project.
-- Security model: every table has row-level security. Fixtures are written
-- only by the sync script (service role). Players write only their own
-- predictions, only before the fixture locks, and nobody can read another
-- player's prediction until it has locked.

create extension if not exists pgcrypto;

-- ---------- Players ----------
create table public.profiles (
  id uuid primary key references auth.users (id) on delete cascade,
  username text not null unique check (username ~ '^[a-z0-9_]{3,20}$'),
  -- The platform is 18+. A profile cannot exist without the player confirming their age.
  adult boolean not null check (adult),
  adult_confirmed_at timestamptz not null default now(),
  created_at timestamptz not null default now()
);
alter table public.profiles enable row level security;
create policy "profiles are public" on public.profiles for select using (true);
create policy "create own profile" on public.profiles for insert to authenticated with check (id = auth.uid());
create policy "rename own profile" on public.profiles for update to authenticated using (id = auth.uid()) with check (id = auth.uid());

-- ---------- Fixtures (written by sync.py with the service role) ----------
create table public.fixtures (
  id text primary key,
  league_id text not null,
  league_name text not null,
  season text not null,
  kickoff_date date not null,
  kickoff_at timestamptz,               -- exact time when known, else null
  home text not null,
  away text not null,
  status text not null default 'scheduled' check (status in ('scheduled', 'finished', 'postponed')),
  home_goals int check (home_goals >= 0),
  away_goals int check (away_goals >= 0),
  lab_home numeric check (lab_home between 0 and 1),
  lab_draw numeric check (lab_draw between 0 and 1),
  lab_away numeric check (lab_away between 0 and 1),
  updated_at timestamptz not null default now(),
  check (status <> 'finished' or (home_goals is not null and away_goals is not null))
);
alter table public.fixtures enable row level security;
create policy "fixtures are public" on public.fixtures for select using (true);
create index fixtures_date on public.fixtures (kickoff_date);

-- The Lab's forecast is frozen once a fixture locks, even for the service role,
-- so it can never be recomputed with knowledge of the result.
create or replace function public.freeze_lab() returns trigger language plpgsql as $$
begin
  if now() >= coalesce(old.kickoff_at, (old.kickoff_date::timestamp at time zone 'UTC')) then
    new.lab_home := old.lab_home; new.lab_draw := old.lab_draw; new.lab_away := old.lab_away;
    new.kickoff_date := old.kickoff_date; new.kickoff_at := old.kickoff_at;
  end if;
  new.updated_at := now();
  return new;
end $$;
create trigger fixtures_freeze_lab before update on public.fixtures for each row execute function public.freeze_lab();

-- A fixture locks at its exact kickoff, or at 00:00 UTC on its date when the
-- time is unknown (conservative: never later than the real kickoff).
create or replace function public.lock_time(f public.fixtures) returns timestamptz
language sql immutable as $$
  select coalesce(f.kickoff_at, (f.kickoff_date::timestamp at time zone 'UTC'))
$$;

create or replace function public.fixture_open(fixture text) returns boolean
language sql stable security definer set search_path = public as $$
  select exists (select 1 from fixtures f where f.id = fixture and f.status = 'scheduled' and now() < lock_time(f))
$$;

-- ---------- Predictions ----------
create table public.predictions (
  user_id uuid not null references public.profiles (id) on delete cascade,
  fixture_id text not null references public.fixtures (id) on delete cascade,
  p_home int not null check (p_home between 0 and 100),
  p_draw int not null check (p_draw between 0 and 100),
  p_away int not null check (p_away between 0 and 100),
  updated_at timestamptz not null default now(),
  primary key (user_id, fixture_id),
  check (p_home + p_draw + p_away = 100)
);
alter table public.predictions enable row level security;
create policy "read own or locked predictions" on public.predictions for select
  using (user_id = auth.uid() or not public.fixture_open(fixture_id));
create policy "predict before lock" on public.predictions for insert to authenticated
  with check (user_id = auth.uid() and public.fixture_open(fixture_id));
create policy "change before lock" on public.predictions for update to authenticated
  using (user_id = auth.uid() and public.fixture_open(fixture_id))
  with check (user_id = auth.uid() and public.fixture_open(fixture_id));
create policy "withdraw before lock" on public.predictions for delete to authenticated
  using (user_id = auth.uid() and public.fixture_open(fixture_id));

create or replace function public.touch_prediction() returns trigger language plpgsql as $$
begin new.updated_at = now(); return new; end $$;
create trigger predictions_touch before update on public.predictions
  for each row execute function public.touch_prediction();

-- ---------- Private mini-leagues ----------
create table public.groups (
  id uuid primary key default gen_random_uuid(),
  name text not null check (char_length(name) between 3 and 40),
  owner uuid not null references public.profiles (id) on delete cascade,
  invite_code text not null unique default upper(substr(encode(gen_random_bytes(6), 'hex'), 1, 8)),
  created_at timestamptz not null default now()
);
create table public.group_members (
  group_id uuid not null references public.groups (id) on delete cascade,
  user_id uuid not null references public.profiles (id) on delete cascade,
  joined_at timestamptz not null default now(),
  primary key (group_id, user_id)
);
alter table public.groups enable row level security;
alter table public.group_members enable row level security;

create or replace function public.is_member(g uuid) returns boolean
language sql stable security definer set search_path = public as $$
  select exists (select 1 from group_members m where m.group_id = g and m.user_id = auth.uid())
$$;
create policy "members see their groups" on public.groups for select using (public.is_member(id) or owner = auth.uid());
create policy "create a group" on public.groups for insert to authenticated with check (owner = auth.uid());
create policy "owner renames" on public.groups for update to authenticated using (owner = auth.uid()) with check (owner = auth.uid());
create policy "owner deletes" on public.groups for delete to authenticated using (owner = auth.uid());
create policy "members see members" on public.group_members for select using (public.is_member(group_id));
create policy "leave a group" on public.group_members for delete to authenticated using (user_id = auth.uid());

-- Owners join their own group automatically.
create or replace function public.add_owner() returns trigger language plpgsql security definer set search_path = public as $$
begin insert into group_members (group_id, user_id) values (new.id, new.owner); return new; end $$;
create trigger groups_add_owner after insert on public.groups for each row execute function public.add_owner();

-- Joining needs the invite code; the code itself is never listed publicly.
create or replace function public.join_group(code text) returns uuid
language plpgsql security definer set search_path = public as $$
declare g uuid;
begin
  if auth.uid() is null then raise exception 'Sign in first'; end if;
  select id into g from groups where invite_code = upper(trim(code));
  if g is null then raise exception 'No league with that code'; end if;
  insert into group_members (group_id, user_id) values (g, auth.uid()) on conflict do nothing;
  return g;
end $$;

-- ---------- Scoring ----------
-- Brier score over the three outcomes (0 perfect, 2 worst). Points are how
-- much better than the Lab's forecast a player did, x100. Proper scoring:
-- reporting your honest probabilities maximizes expected points.
create or replace view public.scored with (security_invoker = true) as
select p.user_id, p.fixture_id, f.league_id, f.season, f.kickoff_date,
       date_trunc('week', f.kickoff_date)::date as round,
       p.p_home, p.p_draw, p.p_away,
       case when f.home_goals > f.away_goals then 0 when f.home_goals = f.away_goals then 1 else 2 end as outcome,
       f.lab_home, f.lab_draw, f.lab_away
from public.predictions p join public.fixtures f on f.id = p.fixture_id
where f.status = 'finished';

create or replace view public.scores with (security_invoker = true) as
select s.*,
  power(p_home / 100.0 - (outcome = 0)::int, 2) + power(p_draw / 100.0 - (outcome = 1)::int, 2)
    + power(p_away / 100.0 - (outcome = 2)::int, 2) as brier,
  power(coalesce(lab_home, 1 / 3.0) - (outcome = 0)::int, 2) + power(coalesce(lab_draw, 1 / 3.0) - (outcome = 1)::int, 2)
    + power(coalesce(lab_away, 1 / 3.0) - (outcome = 2)::int, 2) as lab_brier,
  (greatest(p_home, p_draw, p_away) = case outcome when 0 then p_home when 1 then p_draw else p_away end) as top_pick_right,
  case outcome when 0 then p_home when 1 then p_draw else p_away end as p_outcome,
  case outcome when 0 then lab_home when 1 then lab_draw else lab_away end as lab_outcome
from public.scored s;

create or replace view public.points with (security_invoker = true) as
select sc.*, round(((lab_brier - brier) * 100)::numeric, 2) as points from public.scores sc;

create or replace view public.leaderboard with (security_invoker = true) as
select pr.username, pt.user_id, pt.season, count(*) as predictions, sum(pt.points) as points,
       round(avg(pt.brier)::numeric, 4) as avg_brier, round(avg(pt.top_pick_right::int)::numeric, 4) as hit_rate,
       sum((pt.points > 0)::int) as beat_lab
from public.points pt join public.profiles pr on pr.id = pt.user_id
group by pr.username, pt.user_id, pt.season;

create or replace view public.weekly with (security_invoker = true) as
select pr.username, pt.user_id, pt.round, count(*) as predictions, sum(pt.points) as points
from public.points pt join public.profiles pr on pr.id = pt.user_id
group by pr.username, pt.user_id, pt.round;

-- Consecutive weeks played, ending at the most recent week with a finished fixture.
create or replace view public.streaks with (security_invoker = true) as
with weeks as (select distinct user_id, round from public.scored),
islands as (select user_id, round, round - (row_number() over (partition by user_id order by round) * 7)::int as grp from weeks)
select user_id, count(*) as weeks, max(round) as last_round
from islands group by user_id, grp;

create or replace view public.badges with (security_invoker = true) as
select user_id, 'upset_caller' as badge, fixture_id, kickoff_date from public.points
  where p_outcome >= 50 and lab_outcome < 0.25
union all
select user_id, 'bang_on', fixture_id, kickoff_date from public.points where p_outcome >= 80
union all
select user_id, 'sharp_week', null, round from public.weekly w
  join (select user_id as u, round as r from public.points group by user_id, round having count(*) >= 5) q
  on q.u = w.user_id and q.r = w.round where w.points > 0;

-- Crowd consensus: only from locked predictions, so it never reveals live picks.
create or replace view public.crowd with (security_invoker = true) as
select fixture_id, count(*) as players,
       round(avg(p_home)::numeric, 1) as p_home, round(avg(p_draw)::numeric, 1) as p_draw, round(avg(p_away)::numeric, 1) as p_away
from public.predictions where not public.fixture_open(fixture_id)
group by fixture_id;

-- How many players have locked in for an open fixture (count only, no picks).
create or replace function public.entry_counts(ids text[]) returns table (fixture_id text, players bigint)
language sql stable security definer set search_path = public as $$
  select fixture_id, count(*) from predictions where fixture_id = any(ids) group by fixture_id
$$;

grant usage on schema public to anon, authenticated;
grant select on public.profiles, public.fixtures, public.scored, public.scores, public.points, public.leaderboard,
  public.weekly, public.streaks, public.badges, public.crowd to anon, authenticated;
grant select, insert, update, delete on public.predictions, public.groups, public.group_members to authenticated;
grant select on public.predictions to anon;
grant insert, update on public.profiles to authenticated;
grant execute on function public.join_group(text), public.entry_counts(text[]), public.fixture_open(text), public.lock_time(public.fixtures) to anon, authenticated;
