-- Initial schema. Captures the full current table set.
-- Uses IF NOT EXISTS / ADD COLUMN IF NOT EXISTS so it is safe to run against
-- databases that were created by the legacy in-code init_db().

create table if not exists users (
    id text primary key,
    email text unique not null,
    password_hash text not null,
    native_language text not null default 'ru',
    target_language text not null default 'en',
    email_verified boolean not null default true,
    tts_enabled boolean not null default true,
    tts_voice text not null default '',
    tts_rate real not null default 1,
    tts_pitch real not null default 1,
    tts_volume real not null default 1,
    created_at timestamptz not null default now()
);
alter table users add column if not exists tts_enabled boolean not null default true;
alter table users add column if not exists email_verified boolean not null default true;
alter table users add column if not exists tts_voice text not null default '';
alter table users add column if not exists tts_rate real not null default 1;
alter table users add column if not exists tts_pitch real not null default 1;
alter table users add column if not exists tts_volume real not null default 1;

create table if not exists sessions (
    token text primary key,
    user_id text not null references users(id) on delete cascade,
    created_at timestamptz not null default now()
);

create table if not exists email_verification_codes (
    email text primary key,
    password_hash text not null,
    native_language text not null default 'ru',
    target_language text not null default 'en',
    code_hash text not null,
    attempts integer not null default 0,
    expires_at timestamptz not null,
    created_at timestamptz not null default now()
);

create table if not exists documents (
    id text primary key,
    user_id text not null references users(id) on delete cascade,
    title text not null,
    type text not null,
    language text not null,
    raw_text text not null,
    clean_text text not null,
    created_at timestamptz not null default now()
);

create table if not exists words (
    id text primary key,
    language text not null,
    lemma text not null,
    part_of_speech text not null,
    translation_ru text not null,
    transcription text not null default '',
    frequency_rank integer not null,
    unique(language, lemma)
);
alter table words add column if not exists transcription text not null default '';

create table if not exists user_words (
    id text primary key,
    user_id text not null references users(id) on delete cascade,
    word_id text not null references words(id) on delete cascade,
    status text not null,
    confidence real not null,
    last_seen_at timestamptz,
    last_reviewed_at timestamptz,
    unique(user_id, word_id)
);

create table if not exists phrases (
    id text primary key,
    language text not null,
    phrase text not null,
    base_form text not null,
    type text not null,
    translation_ru text not null,
    unique(language, base_form)
);

create table if not exists user_phrases (
    id text primary key,
    user_id text not null references users(id) on delete cascade,
    phrase_id text not null references phrases(id) on delete cascade,
    status text not null,
    confidence real not null,
    unique(user_id, phrase_id)
);

create table if not exists analyses (
    id text primary key,
    document_id text not null references documents(id) on delete cascade,
    user_id text not null references users(id) on delete cascade,
    total_words integer not null,
    unique_words integer not null,
    known_words integer not null,
    unknown_words integer not null,
    ignored_words integer not null,
    coverage_percent integer not null,
    unique_coverage_percent integer not null,
    projected_coverage_percent integer not null,
    payload jsonb not null,
    created_at timestamptz not null default now(),
    unique(document_id)
);

create table if not exists reviews (
    id text primary key,
    user_id text not null references users(id) on delete cascade,
    word_id text not null references words(id) on delete cascade,
    grade integer not null,
    created_at timestamptz not null default now()
);

create table if not exists learn_blocks (
    id text primary key,
    user_id text not null references users(id) on delete cascade,
    title text not null,
    frequency_filter text not null default 'all',
    payload jsonb not null,
    created_at timestamptz not null default now()
);
alter table learn_blocks add column if not exists frequency_filter text not null default 'all';
create index if not exists idx_learn_blocks_user_created on learn_blocks(user_id, created_at, id);

create table if not exists wordnet_entries (
    id bigserial primary key,
    lemma text not null,
    pos text not null,
    definition text not null,
    synonyms text[] not null default '{}',
    source_offset text not null,
    sense_rank integer not null default 9999,
    created_at timestamptz not null default now(),
    unique(lemma, pos, source_offset)
);
alter table wordnet_entries add column if not exists sense_rank integer not null default 9999;
create index if not exists idx_wordnet_entries_lemma on wordnet_entries(lemma);
create index if not exists idx_wordnet_entries_lemma_pos on wordnet_entries(lemma, pos);

create table if not exists muse_translations (
    id bigserial primary key,
    source text not null,
    target text not null,
    rank integer not null,
    created_at timestamptz not null default now(),
    unique(source, target)
);
create index if not exists idx_muse_translations_source_rank on muse_translations(source, rank);

create table if not exists phrase_dictionary (
    id bigserial primary key,
    language text not null default 'en',
    base_form text not null,
    type text not null,
    translation_ru text not null default 'перевод уточняется',
    source text not null default 'manual',
    created_at timestamptz not null default now(),
    unique(language, base_form, type)
);
create index if not exists idx_phrase_dictionary_language_type on phrase_dictionary(language, type);

create table if not exists system_terms (
    id bigserial primary key,
    term_type text not null,
    term text not null,
    source text not null default 'system',
    created_at timestamptz not null default now(),
    unique(term_type, term)
);
create index if not exists idx_system_terms_type on system_terms(term_type);
