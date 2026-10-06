-- Behaviour tests for schema.sql. Run against a database with test_stub.sql + schema.sql.
\set ON_ERROR_STOP on
grant all on all tables in schema public to service_role;
insert into auth.users values ('00000000-0000-0000-0000-00000000000a', 'a@x'), ('00000000-0000-0000-0000-00000000000b', 'b@x');
-- open (future), locked (today 00:00 UTC has passed), finished (past) fixtures
insert into public.fixtures (id, league_id, league_name, season, kickoff_date, home, away, lab_home, lab_draw, lab_away) values
 ('open', 'en.1', 'EPL', '2026-27', current_date + 3, 'A', 'B', .5, .3, .2),
 ('locked', 'en.1', 'EPL', '2026-27', current_date, 'C', 'D', .4, .3, .3),
 ('done', 'en.1', 'EPL', '2026-27', current_date - 3, 'E', 'F', .6, .25, .15);
update public.fixtures set status = 'finished', home_goals = 0, away_goals = 2 where id = 'done';

create function pg_temp.as_user(u text) returns void language plpgsql as $$
begin perform set_config('request.jwt.claim.sub', u, false); end $$;

-- Player A
set role authenticated; select pg_temp.as_user('00000000-0000-0000-0000-00000000000a');
insert into public.profiles (id, username, adult) values (auth.uid(), 'alice', true);
insert into public.predictions (user_id, fixture_id, p_home, p_draw, p_away) values (auth.uid(), 'open', 60, 25, 15);
do $$ begin
  begin update public.profiles set adult = false where id = auth.uid(); raise exception 'FAIL: profile without 18+ confirmation';
  exception when check_violation then null; end;
  begin insert into public.predictions values (auth.uid(), 'locked', 50, 30, 20); raise exception 'FAIL: predicted a locked fixture';
  exception when insufficient_privilege then null; end;
  begin insert into public.predictions values (auth.uid(), 'open', 50, 30, 30); raise exception 'FAIL: sum not 100 accepted';
  exception when check_violation or unique_violation then null; end;
  begin insert into public.predictions values ('00000000-0000-0000-0000-00000000000b', 'open', 50, 30, 20); raise exception 'FAIL: wrote for another user';
  exception when insufficient_privilege or foreign_key_violation then null; end;
  begin insert into public.fixtures (id, league_id, league_name, season, kickoff_date, home, away) values ('x','en.1','x','x',current_date,'X','Y');
    raise exception 'FAIL: player wrote a fixture';
  exception when insufficient_privilege then null; end;
end $$;
update public.predictions set p_home = 55, p_draw = 30 where fixture_id = 'open';
reset role;

-- Seed predictions made before lock (as service role) on the locked and finished fixtures.
insert into public.profiles (id, username, adult) values ('00000000-0000-0000-0000-00000000000b', 'bob', true);
insert into public.predictions values
 ('00000000-0000-0000-0000-00000000000a', 'done', 20, 30, 50, now()), ('00000000-0000-0000-0000-00000000000b', 'done', 70, 20, 10, now()),
 ('00000000-0000-0000-0000-00000000000b', 'locked', 40, 30, 30, now()), ('00000000-0000-0000-0000-00000000000b', 'open', 10, 10, 80, now());

-- Player A cannot see B's open pick, can see locked ones, cannot edit locked ones.
set role authenticated; select pg_temp.as_user('00000000-0000-0000-0000-00000000000a');
do $$ declare n int; begin
  select count(*) into n from public.predictions where fixture_id = 'open';
  if n <> 1 then raise exception 'FAIL: saw % open predictions (expected own only)', n; end if;
  select count(*) into n from public.predictions where fixture_id in ('locked', 'done');
  if n <> 3 then raise exception 'FAIL: saw % locked predictions, expected 3', n; end if;
  update public.predictions set p_home = 30, p_draw = 30, p_away = 40 where fixture_id = 'done';
  get diagnostics n = row_count; if n <> 0 then raise exception 'FAIL: edited a finished prediction'; end if;
  select count(*) into n from public.crowd where fixture_id = 'open';
  if n <> 0 then raise exception 'FAIL: crowd revealed an open fixture'; end if;
  select players into n from public.entry_counts(array['open']);
  if n <> 2 then raise exception 'FAIL: entry count %', n; end if;
end $$;

-- Scoring: outcome away (0-2). Alice 20/30/50: brier .04+.09+.25=.38; lab .6/.25/.15: .36+.0625+.7225=1.145
do $$ declare pa numeric; pb numeric; begin
  select points into pa from public.points where fixture_id = 'done' and user_id = '00000000-0000-0000-0000-00000000000a';
  select points into pb from public.points where fixture_id = 'done' and user_id = '00000000-0000-0000-0000-00000000000b';
  if pa <> 76.5 then raise exception 'FAIL: alice points %', pa; end if;
  if pb >= 0 then raise exception 'FAIL: bob should trail the lab, got %', pb; end if;
  if (select username from public.leaderboard order by points desc limit 1) <> 'alice' then raise exception 'FAIL: leaderboard order'; end if;
  if not exists (select 1 from public.badges where badge = 'upset_caller') then null; end if;
end $$;

-- Groups: create, join with code, privacy.
insert into public.groups (name, owner) values ('Lagos Lads', auth.uid());
reset role;
do $$ declare code text; begin
  select invite_code into code from public.groups where name = 'Lagos Lads';
  perform set_config('test.code', code, false);
end $$;
set role authenticated; select pg_temp.as_user('00000000-0000-0000-0000-00000000000b');
do $$ declare n int; begin
  select count(*) into n from public.groups; if n <> 0 then raise exception 'FAIL: non-member saw a group'; end if;
  perform public.join_group(current_setting('test.code'));
  select count(*) into n from public.group_members; if n <> 2 then raise exception 'FAIL: members %', n; end if;
  begin perform public.join_group('NOPE1234'); raise exception 'FAIL: bad code accepted';
  exception when raise_exception then if sqlerrm like 'FAIL%' then raise; end if; end;
end $$;
-- Anonymous visitors: public leaderboard yes, open picks no.
set role anon; select pg_temp.as_user('');
do $$ declare n int; begin
  select count(*) into n from public.predictions where fixture_id = 'open'; if n <> 0 then raise exception 'FAIL: anon saw open picks'; end if;
  select count(*) into n from public.leaderboard; if n < 2 then raise exception 'FAIL: anon leaderboard %', n; end if;
end $$;
reset role;
-- The Lab forecast cannot change after lock, even for the service role.
update public.fixtures set lab_home = .9, lab_draw = .05, lab_away = .05 where id = 'done';
update public.fixtures set lab_home = .7, lab_draw = .2, lab_away = .1 where id = 'open';
do $$ begin
  if (select lab_home from public.fixtures where id = 'done') <> .6 then raise exception 'FAIL: locked lab forecast changed'; end if;
  if (select lab_home from public.fixtures where id = 'open') <> .7 then raise exception 'FAIL: open lab forecast not updated'; end if;
end $$;
select 'ALL RULE TESTS PASSED' as result;
