-- AI enrichment support: a persistent response cache (to avoid paying for
-- repeat calls) and a per-user daily usage counter (for quotas).

create table if not exists ai_cache (
    cache_key text primary key,
    task text not null,
    payload jsonb not null,
    created_at timestamptz not null default now()
);
create index if not exists idx_ai_cache_task on ai_cache(task);

create table if not exists ai_usage (
    user_id text not null references users(id) on delete cascade,
    usage_day date not null,
    count integer not null default 0,
    unique(user_id, usage_day)
);
create index if not exists idx_ai_usage_user_day on ai_usage(user_id, usage_day);
