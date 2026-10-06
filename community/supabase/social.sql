-- Social platform v1: friends, moderated public rooms, friend-only direct messages,
-- game challenges, and safety tools. Run after schema.sql.
-- Every rule is enforced here with row-level security, not in the browser.

-- ---------- Safety primitives ----------
create table public.moderators (user_id uuid primary key references public.profiles (id) on delete cascade);
create table public.bans (
  user_id uuid primary key references public.profiles (id) on delete cascade,
  until timestamptz not null, reason text not null, by uuid references public.profiles (id), created_at timestamptz not null default now()
);
create table public.blocks (
  blocker uuid not null references public.profiles (id) on delete cascade,
  blocked uuid not null references public.profiles (id) on delete cascade,
  created_at timestamptz not null default now(),
  primary key (blocker, blocked), check (blocker <> blocked)
);
alter table public.moderators enable row level security;
alter table public.bans enable row level security;
alter table public.blocks enable row level security;

create or replace function public.is_moderator(u uuid default auth.uid()) returns boolean
language sql stable security definer set search_path = public as $$ select exists (select 1 from moderators where user_id = u) $$;
create or replace function public.is_banned(u uuid default auth.uid()) returns boolean
language sql stable security definer set search_path = public as $$ select exists (select 1 from bans where user_id = u and until > now()) $$;
-- Either side blocking the other cuts all contact.
create or replace function public.blocked_between(a uuid, b uuid) returns boolean
language sql stable security definer set search_path = public as $$
  select exists (select 1 from blocks where (blocker = a and blocked = b) or (blocker = b and blocked = a))
$$;
-- Signed in, has an 18+ profile, not banned.
create or replace function public.can_socialise(u uuid default auth.uid()) returns boolean
language sql stable security definer set search_path = public as $$
  select u is not null and exists (select 1 from profiles where id = u and adult) and not is_banned(u)
$$;

create policy "moderators list" on public.moderators for select using (public.is_moderator());
create policy "see own ban" on public.bans for select using (user_id = auth.uid() or public.is_moderator());
create policy "moderators ban" on public.bans for all using (public.is_moderator()) with check (public.is_moderator());
create policy "see own blocks" on public.blocks for select using (blocker = auth.uid());
create policy "block someone" on public.blocks for insert to authenticated with check (blocker = auth.uid());
create policy "unblock" on public.blocks for delete to authenticated using (blocker = auth.uid());

-- ---------- Friends ----------
create table public.friend_requests (
  sender uuid not null references public.profiles (id) on delete cascade,
  recipient uuid not null references public.profiles (id) on delete cascade,
  status text not null default 'pending' check (status in ('pending', 'accepted', 'declined')),
  created_at timestamptz not null default now(), responded_at timestamptz,
  primary key (sender, recipient), check (sender <> recipient)
);
alter table public.friend_requests enable row level security;
create policy "see requests involving me" on public.friend_requests for select using (auth.uid() in (sender, recipient));
create policy "send a request" on public.friend_requests for insert to authenticated with check (
  sender = auth.uid() and status = 'pending' and public.can_socialise() and public.can_socialise(recipient)
  and not public.blocked_between(sender, recipient)
  and not exists (select 1 from public.friend_requests r where r.sender = recipient and r.recipient = sender));
create policy "answer a request" on public.friend_requests for update to authenticated
  using (recipient = auth.uid() and status = 'pending') with check (recipient = auth.uid() and status in ('accepted', 'declined'));
create policy "cancel or unfriend" on public.friend_requests for delete to authenticated using (auth.uid() in (sender, recipient));

create or replace function public.are_friends(a uuid, b uuid) returns boolean
language sql stable security definer set search_path = public as $$
  select exists (select 1 from friend_requests where status = 'accepted' and ((sender = a and recipient = b) or (sender = b and recipient = a)))
    and not blocked_between(a, b)
$$;
create or replace view public.my_friends with (security_invoker = true) as
select case when r.sender = auth.uid() then r.recipient else r.sender end as friend_id, p.username, r.responded_at as since
from public.friend_requests r
join public.profiles p on p.id = case when r.sender = auth.uid() then r.recipient else r.sender end
where r.status = 'accepted' and auth.uid() in (r.sender, r.recipient) and not public.blocked_between(r.sender, r.recipient);

-- Blocking someone also ends the friendship and any pending request.
create or replace function public.on_block() returns trigger language plpgsql security definer set search_path = public as $$
begin
  delete from friend_requests where (sender = new.blocker and recipient = new.blocked) or (sender = new.blocked and recipient = new.blocker);
  return new;
end $$;
create trigger blocks_end_friendship after insert on public.blocks for each row execute function public.on_block();

-- ---------- Rooms and messages ----------
create table public.rooms (
  id uuid primary key default gen_random_uuid(),
  kind text not null check (kind in ('public', 'dm')),
  slug text unique,                         -- public rooms only
  title text not null,
  created_at timestamptz not null default now(),
  check ((kind = 'public') = (slug is not null))
);
create table public.room_members (
  room_id uuid not null references public.rooms (id) on delete cascade,
  user_id uuid not null references public.profiles (id) on delete cascade,
  primary key (room_id, user_id)
);
alter table public.rooms enable row level security;
alter table public.room_members enable row level security;

create or replace function public.in_room(r uuid, u uuid default auth.uid()) returns boolean
language sql stable security definer set search_path = public as $$
  select exists (select 1 from rooms where id = r and kind = 'public') or exists (select 1 from room_members where room_id = r and user_id = u)
$$;
create policy "see public rooms and my DMs" on public.rooms for select using (kind = 'public' or public.in_room(id));
create policy "see members of my rooms" on public.room_members for select using (public.in_room(room_id));

-- Direct messages: only between mutual friends. Returns the existing room if there is one.
create or replace function public.open_dm(friend uuid) returns uuid
language plpgsql security definer set search_path = public as $$
declare r uuid;
begin
  if not can_socialise() then raise exception 'Sign in with an 18+ profile first'; end if;
  if not are_friends(auth.uid(), friend) then raise exception 'You can only message friends'; end if;
  select m1.room_id into r from room_members m1 join room_members m2 on m1.room_id = m2.room_id join rooms on rooms.id = m1.room_id
    where rooms.kind = 'dm' and m1.user_id = auth.uid() and m2.user_id = friend limit 1;
  if r is not null then return r; end if;
  insert into rooms (kind, title) values ('dm', 'Direct message') returning id into r;
  insert into room_members (room_id, user_id) values (r, auth.uid()), (r, friend);
  return r;
end $$;

create table public.messages (
  id bigint generated always as identity primary key,
  room_id uuid not null references public.rooms (id) on delete cascade,
  author uuid not null references public.profiles (id) on delete cascade,
  body text not null check (char_length(body) between 1 and 500),
  created_at timestamptz not null default now(),
  hidden boolean not null default false,
  hidden_reason text
);
create index messages_room_time on public.messages (room_id, created_at desc);
alter table public.messages enable row level security;

-- Readers never see hidden messages (except moderators) or anything from people they've blocked.
create policy "read messages" on public.messages for select using (
  public.can_socialise() and public.in_room(room_id)
  and (not hidden or public.is_moderator())
  and not public.blocked_between(auth.uid(), author));
create policy "post messages" on public.messages for insert to authenticated with check (
  author = auth.uid() and public.can_socialise() and public.in_room(room_id) and not hidden
  -- In a DM, the other person must still be a friend (and not blocking you).
  and not exists (select 1 from public.room_members m join public.rooms r on r.id = m.room_id
                  where m.room_id = messages.room_id and r.kind = 'dm' and m.user_id <> auth.uid() and not public.are_friends(auth.uid(), m.user_id)));
create policy "delete own message" on public.messages for delete to authenticated using (author = auth.uid());

-- Server-side guard rails: word filter and rate limit (5 messages per 10 seconds).
create or replace function public.guard_message() returns trigger language plpgsql security definer set search_path = public as $$
begin
  if (select count(*) from messages where author = new.author and created_at > now() - interval '10 seconds') >= 5 then
    raise exception 'Slow down: too many messages';
  end if;
  new.body := regexp_replace(trim(new.body), '\m(f+u+c+k+\w*|sh[i1]t\w*|c+u+n+t+\w*|b[i1]tch\w*|n[i1]gg\w*|f[a4]g+\w*|wh[o0]re\w*|slut\w*|retard\w*)\M', '****', 'gi');
  new.created_at := now(); new.hidden := false; new.hidden_reason := null;
  return new;
end $$;
create trigger messages_guard before insert on public.messages for each row execute function public.guard_message();

-- ---------- Reports and moderation ----------
create table public.reports (
  id bigint generated always as identity primary key,
  reporter uuid not null references public.profiles (id) on delete cascade,
  message_id bigint references public.messages (id) on delete cascade,
  reported_user uuid references public.profiles (id) on delete cascade,
  reason text not null check (reason in ('abuse', 'hate', 'spam', 'scam', 'sexual', 'underage', 'other')),
  note text check (char_length(note) <= 300),
  status text not null default 'open' check (status in ('open', 'actioned', 'dismissed')),
  created_at timestamptz not null default now(),
  check (message_id is not null or reported_user is not null),
  unique (reporter, message_id)
);
alter table public.reports enable row level security;
create policy "file a report" on public.reports for insert to authenticated with check (reporter = auth.uid() and public.can_socialise() and status = 'open');
create policy "see own or all as moderator" on public.reports for select using (reporter = auth.uid() or public.is_moderator());
create policy "moderators resolve" on public.reports for update using (public.is_moderator()) with check (public.is_moderator());

-- Three distinct reports hide a message automatically until a moderator reviews it.
create or replace function public.auto_hide() returns trigger language plpgsql security definer set search_path = public as $$
begin
  if new.message_id is not null and (select count(distinct reporter) from reports where message_id = new.message_id) >= 3 then
    update messages set hidden = true, hidden_reason = 'auto: 3 reports' where id = new.message_id;
  end if;
  return new;
end $$;
create trigger reports_auto_hide after insert on public.reports for each row execute function public.auto_hide();

create or replace function public.moderate_message(msg bigint, hide boolean, reason text default null) returns void
language plpgsql security definer set search_path = public as $$
begin
  if not is_moderator() then raise exception 'Moderators only'; end if;
  update messages set hidden = hide, hidden_reason = case when hide then coalesce(reason, 'moderator') end where id = msg;
  update reports set status = case when hide then 'actioned' else 'dismissed' end where message_id = msg and status = 'open';
end $$;
create or replace function public.ban_user(target uuid, hours int, reason text) returns void
language plpgsql security definer set search_path = public as $$
begin
  if not is_moderator() then raise exception 'Moderators only'; end if;
  insert into bans (user_id, until, reason, by) values (target, now() + make_interval(hours => hours), reason, auth.uid())
    on conflict (user_id) do update set until = excluded.until, reason = excluded.reason, by = excluded.by;
  update messages set hidden = true, hidden_reason = 'author banned' where author = target and created_at > now() - interval '24 hours';
end $$;

-- ---------- Challenges (play a friend) ----------
create table public.challenges (
  id uuid primary key default gen_random_uuid(),
  sender uuid not null references public.profiles (id) on delete cascade,
  recipient uuid not null references public.profiles (id) on delete cascade,
  game text not null check (game in ('kickabout', 'spotkick')),
  mode text not null default '5v5' check (mode in ('3v3', '5v5', '11v11')),
  room_code text not null check (room_code ~ '^[A-Z0-9]{6}$'),
  status text not null default 'pending' check (status in ('pending', 'accepted', 'declined', 'expired')),
  created_at timestamptz not null default now(),
  expires_at timestamptz not null default now() + interval '15 minutes',
  check (sender <> recipient)
);
alter table public.challenges enable row level security;
create policy "see my challenges" on public.challenges for select using (auth.uid() in (sender, recipient));
create policy "challenge a friend" on public.challenges for insert to authenticated with check (
  sender = auth.uid() and status = 'pending' and public.can_socialise() and public.are_friends(sender, recipient)
  and (select count(*) from public.challenges c where c.sender = auth.uid() and c.created_at > now() - interval '1 minute') < 3);
create policy "answer a challenge" on public.challenges for update to authenticated
  using (recipient = auth.uid() and status = 'pending' and expires_at > now()) with check (recipient = auth.uid() and status in ('accepted', 'declined'));

-- Live updates: stream new messages, friend requests and challenges to subscribers.
-- Row-level security still applies to what each subscriber receives. The publication only
-- exists on Supabase, so this is skipped elsewhere (e.g. local tests).
do $$ begin
  if exists (select 1 from pg_publication where pubname = 'supabase_realtime') then
    alter publication supabase_realtime add table public.messages, public.friend_requests, public.challenges;
  end if;
end $$;

-- ---------- Seed public rooms ----------
insert into public.rooms (kind, slug, title) values
  ('public', 'general', 'General'), ('public', 'premier-league', 'Premier League'), ('public', 'la-liga', 'La Liga'),
  ('public', 'serie-a', 'Serie A'), ('public', 'bundesliga', 'Bundesliga'), ('public', 'ligue-1', 'Ligue 1'),
  ('public', 'kickabout', 'Kickabout'), ('public', 'spot-kick', 'Spot Kick');

grant select on public.rooms, public.room_members, public.messages, public.my_friends, public.friend_requests,
  public.challenges, public.reports, public.blocks, public.bans, public.moderators to authenticated;
grant insert, delete on public.messages, public.blocks to authenticated;
grant insert, update, delete on public.friend_requests to authenticated;
grant insert, update on public.challenges, public.reports to authenticated;
grant insert, update, delete on public.bans to authenticated;
grant execute on function public.open_dm(uuid), public.moderate_message(bigint, boolean, text), public.ban_user(uuid, int, text),
  public.are_friends(uuid, uuid), public.can_socialise(uuid), public.is_moderator(uuid), public.in_room(uuid, uuid),
  public.blocked_between(uuid, uuid), public.is_banned(uuid) to authenticated;
