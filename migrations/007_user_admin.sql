-- Admin moderation: allow blocking a user from logging in. Idempotent.

alter table users add column if not exists is_blocked boolean not null default false;
