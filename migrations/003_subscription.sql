-- Premium subscription support: plan fields on users and a payments ledger.
-- Idempotent (IF NOT EXISTS) so it is safe to re-run.

alter table users add column if not exists plan text not null default 'free';
alter table users add column if not exists premium_until timestamptz;
alter table users add column if not exists yookassa_payment_method_id text;
-- Whether the subscription auto-renews. Cancelling clears this but keeps access
-- until premium_until.
alter table users add column if not exists subscription_auto_renew boolean not null default false;

create table if not exists payments (
    id text primary key,
    user_id text not null references users(id) on delete cascade,
    yookassa_id text unique,
    amount numeric(10, 2) not null default 0,
    currency text not null default 'RUB',
    status text not null default 'pending',
    period_days integer not null default 30,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now()
);
create index if not exists idx_payments_user on payments(user_id, created_at);
create index if not exists idx_payments_yookassa on payments(yookassa_id);
