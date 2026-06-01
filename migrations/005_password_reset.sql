-- Password recovery: flag set when a user logs in with a temporary password,
-- forcing them to choose a new one. Idempotent.

alter table users add column if not exists must_change_password boolean not null default false;
