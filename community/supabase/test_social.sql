-- Behaviour tests for social.sql (run after test_stub.sql, schema.sql, social.sql).
\set ON_ERROR_STOP on
create function pg_temp.as_user(u text) returns void language plpgsql as $$ begin perform set_config('request.jwt.claim.sub', u, false); end $$;
insert into auth.users values ('00000000-0000-0000-0000-0000000000a1', 'a'), ('00000000-0000-0000-0000-0000000000b2', 'b'),
  ('00000000-0000-0000-0000-0000000000c3', 'c'), ('00000000-0000-0000-0000-0000000000d4', 'd'), ('00000000-0000-0000-0000-0000000000e5', 'e');
insert into public.profiles (id, username, adult) values ('00000000-0000-0000-0000-0000000000a1', 'ada', true), ('00000000-0000-0000-0000-0000000000b2', 'ben', true),
  ('00000000-0000-0000-0000-0000000000c3', 'cyd', true), ('00000000-0000-0000-0000-0000000000d4', 'mod', true), ('00000000-0000-0000-0000-0000000000e5', 'eve', true);
insert into public.moderators values ('00000000-0000-0000-0000-0000000000d4');
grant all on all tables in schema public to service_role;
\set A '00000000-0000-0000-0000-0000000000a1'
\set B '00000000-0000-0000-0000-0000000000b2'
\set C '00000000-0000-0000-0000-0000000000c3'
\set D '00000000-0000-0000-0000-0000000000d4'
\set E '00000000-0000-0000-0000-0000000000e5'
create temp table ids as select :'A'::uuid a, :'B'::uuid b, :'C'::uuid c, :'D'::uuid d, :'E'::uuid e,
  (select id from public.rooms where slug = 'general') general;
grant select on ids to authenticated, anon;

-- Ada friends Ben; Ben accepts.
set role authenticated; select pg_temp.as_user(:'A');
insert into public.friend_requests (sender, recipient) values (:'A', :'B');
do $$ begin
  begin insert into public.friend_requests (sender, recipient) values ((select a from ids), (select a from ids)); raise exception 'FAIL: self friend';
  exception when check_violation or insufficient_privilege then null; end;
  begin perform public.open_dm((select b from ids)); raise exception 'FAIL: DM before friendship';
  exception when raise_exception then if sqlerrm like 'FAIL%' then raise; end if; end;
end $$;
select pg_temp.as_user(:'B');
update public.friend_requests set status = 'accepted', responded_at = now() where sender = :'A';
do $$ begin if (select count(*) from public.my_friends) <> 1 then raise exception 'FAIL: friendship not listed'; end if; end $$;

-- Ada opens a DM with Ben (same room both ways) and posts; the filter and rate limit apply.
select pg_temp.as_user(:'A');
create temp table dm as select public.open_dm((select b from ids)) id;
grant select on dm to authenticated;
do $$ declare again uuid; begin
  again := public.open_dm((select b from ids));
  if again <> (select id from dm) then raise exception 'FAIL: second DM room created'; end if;
  insert into public.messages (room_id, author, body) values ((select id from dm), auth.uid(), 'You lot are shit at defending');
  if (select body from public.messages order by id desc limit 1) <> 'You lot are **** at defending' then raise exception 'FAIL: word filter'; end if;
  insert into public.messages (room_id, author, body) values ((select general from ids), auth.uid(), 'hello general');
  for i in 1..3 loop insert into public.messages (room_id, author, body) values ((select general from ids), auth.uid(), 'spam ' || i); end loop;
  begin insert into public.messages (room_id, author, body) values ((select general from ids), auth.uid(), 'one too many'); raise exception 'FAIL: rate limit';
  exception when raise_exception then if sqlerrm like 'FAIL%' then raise; end if; end;
  begin insert into public.messages (room_id, author, body) values ((select general from ids), (select b from ids), 'impersonation'); raise exception 'FAIL: posted as someone else';
  exception when insufficient_privilege then null; end;
end $$;

-- Cy (not a friend) cannot read or post in the DM, but can use public rooms.
select pg_temp.as_user(:'C');
do $$ begin
  if (select count(*) from public.messages where room_id = (select id from dm)) <> 0 then raise exception 'FAIL: outsider read a DM'; end if;
  begin insert into public.messages (room_id, author, body) values ((select id from dm), auth.uid(), 'let me in'); raise exception 'FAIL: outsider posted in DM';
  exception when insufficient_privilege then null; end;
  if (select count(*) from public.messages where room_id = (select general from ids)) < 4 then raise exception 'FAIL: public room not readable'; end if;
  begin insert into public.challenges (sender, recipient, game, room_code) values (auth.uid(), (select a from ids), 'kickabout', 'ABC123'); raise exception 'FAIL: challenged a non-friend';
  exception when insufficient_privilege then null; end;
end $$;

-- Ben challenges Ada; Ada accepts.
select pg_temp.as_user(:'B');
insert into public.challenges (sender, recipient, game, mode, room_code) values (:'B', :'A', 'kickabout', '3v3', 'KICK42');
select pg_temp.as_user(:'A');
update public.challenges set status = 'accepted' where recipient = :'A';
do $$ begin if (select status from public.challenges limit 1) <> 'accepted' then raise exception 'FAIL: challenge accept'; end if; end $$;

-- Age earlier messages so the rate limit doesn't mask the access rules being tested next.
reset role; update public.messages set created_at = created_at - interval '1 minute'; set role authenticated; select pg_temp.as_user(:'A');
-- Ada blocks Ben: friendship ends, DM posting stops, and each stops seeing the other's messages.
insert into public.blocks (blocker, blocked) values (:'A', :'B');
do $$ begin
  if (select count(*) from public.my_friends) <> 0 then raise exception 'FAIL: still friends after block'; end if;
  begin insert into public.messages (room_id, author, body) values ((select id from dm), auth.uid(), 'after block'); raise exception 'FAIL: DM after block';
  exception when insufficient_privilege then null; end;
end $$;
select pg_temp.as_user(:'B');
do $$ begin
  if exists (select 1 from public.messages where author = (select a from ids)) then raise exception 'FAIL: blocked user sees blocker messages'; end if;
  begin insert into public.friend_requests (sender, recipient) values (auth.uid(), (select a from ids)); raise exception 'FAIL: re-friend after block';
  exception when insufficient_privilege then null; end;
end $$;

-- Three reports auto-hide Eve's message; a moderator can review and ban.
select pg_temp.as_user(:'E');
insert into public.messages (room_id, author, body) values ((select general from ids), :'E', 'cheap boots, DM me your card number');
reset role;
create temp table bad as select id from public.messages where author = :'E';
grant select on bad to authenticated;
set role authenticated;
select pg_temp.as_user(:'B'); insert into public.reports (reporter, message_id, reason) values (:'B', (select id from bad), 'scam');
select pg_temp.as_user(:'C'); insert into public.reports (reporter, message_id, reason) values (:'C', (select id from bad), 'scam');
do $$ begin if exists (select 1 from public.messages where hidden) then raise exception 'FAIL: hidden too early'; end if;
  if (select count(*) from public.reports) <> 1 then raise exception 'FAIL: saw other people''s reports'; end if; end $$;
select pg_temp.as_user(:'A'); insert into public.reports (reporter, message_id, reason) values (:'A', (select id from bad), 'scam');
do $$ begin if exists (select 1 from public.messages where id = (select id from bad)) then raise exception 'FAIL: auto-hidden message still visible'; end if; end $$;
do $$ begin perform public.ban_user((select e from ids), 24, 'scam'); raise exception 'FAIL: non-moderator banned';
  exception when raise_exception then if sqlerrm like 'FAIL%' then raise; end if; end $$;
select pg_temp.as_user(:'D');
do $$ begin
  if not exists (select 1 from public.messages where id = (select id from bad)) then raise exception 'FAIL: moderator cannot review hidden message'; end if;
  if (select count(*) from public.reports) <> 3 then raise exception 'FAIL: moderator report queue'; end if;
  perform public.ban_user((select e from ids), 24, 'scam');
end $$;
select pg_temp.as_user(:'E');
do $$ begin
  begin insert into public.messages (room_id, author, body) values ((select general from ids), auth.uid(), 'I am back'); raise exception 'FAIL: banned user posted';
  exception when insufficient_privilege then null; end;
  if exists (select 1 from public.messages) then raise exception 'FAIL: banned user can still read'; end if;
end $$;

-- Signed-out visitors see nothing social.
set role anon; select pg_temp.as_user('');
do $$ begin
  begin perform 1 from public.messages limit 1; raise exception 'FAIL: anon read messages';
  exception when insufficient_privilege then null; end;
end $$;
reset role;
select 'ALL SOCIAL TESTS PASSED' as result;
