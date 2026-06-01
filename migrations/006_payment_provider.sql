-- Multi-provider billing: tag each payment with its provider. The yookassa_id
-- column now holds the provider's payment/invoice id generically. Idempotent.

alter table payments add column if not exists provider text not null default 'yookassa';
create index if not exists idx_payments_provider on payments(provider);
