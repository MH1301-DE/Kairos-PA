-- =====================================================================
-- Kairos — Schema-Entwurf (Postgres 16 + TimescaleDB + pgvector)
--
-- Status: Entwurf zur Diskussion. Nicht vollständig, aber lauffähig für
-- die Kernpfade. Produktiv wird das über Alembic-Migrationen verwaltet.
-- =====================================================================

CREATE EXTENSION IF NOT EXISTS timescaledb;
CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS pgcrypto;

-- ---------------------------------------------------------------------
-- IDENTITY
-- ---------------------------------------------------------------------

CREATE TABLE app_user (
    id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    email           text NOT NULL UNIQUE,
    display_name    text NOT NULL,
    home_timezone   text NOT NULL DEFAULT 'Europe/Berlin',
    birth_date      date,
    sex             text CHECK (sex IN ('m','f','x')),
    height_cm       smallint,
    hr_max          smallint,
    hr_rest_manual  smallint,
    role            text NOT NULL DEFAULT 'user' CHECK (role IN ('user','admin')),
    dek_wrapped     bytea,            -- pro Nutzer verschlüsselter Data Encryption Key
    created_at      timestamptz NOT NULL DEFAULT now(),
    deleted_at      timestamptz
);

CREATE TABLE user_setting (
    user_id  uuid REFERENCES app_user(id) ON DELETE CASCADE,
    key      text,
    value    jsonb NOT NULL,
    PRIMARY KEY (user_id, key)
);

-- Verbindung zu einem externen Dienst
CREATE TABLE connection (
    id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id         uuid NOT NULL REFERENCES app_user(id) ON DELETE CASCADE,
    connector       text NOT NULL,                 -- 'garmin' | 'google' | 'caldav' | ...
    external_account text,
    status          text NOT NULL DEFAULT 'active'
                    CHECK (status IN ('active','reauth_required','disabled','error')),
    credentials_enc bytea,                         -- mit dem DEK des Nutzers verschlüsselt
    config          jsonb NOT NULL DEFAULT '{}',
    connected_at    timestamptz NOT NULL DEFAULT now(),
    last_ok_at      timestamptz,
    last_error      text,
    UNIQUE (user_id, connector, external_account)
);

-- ---------------------------------------------------------------------
-- PLATFORM: Raw-Zone, Sync-Zustand, Audit
-- ---------------------------------------------------------------------

CREATE TABLE raw_payload (
    id            bigserial PRIMARY KEY,
    user_id       uuid NOT NULL REFERENCES app_user(id) ON DELETE CASCADE,
    connector     text NOT NULL,
    kind          text NOT NULL,                   -- 'sleep' | 'hr_intraday' | ...
    window_start  timestamptz NOT NULL,
    window_end    timestamptz NOT NULL,
    fetched_at    timestamptz NOT NULL DEFAULT now(),
    content_hash  bytea NOT NULL,
    payload_gzip  bytea,                           -- NULL, wenn im Object Store
    object_key    text,
    UNIQUE (user_id, connector, kind, window_start, content_hash)
);
CREATE INDEX ON raw_payload (user_id, connector, kind, window_start DESC);

CREATE TABLE sync_state (
    user_id                uuid NOT NULL REFERENCES app_user(id) ON DELETE CASCADE,
    connector              text NOT NULL,
    kind                   text NOT NULL,
    synced_through         timestamptz,            -- Watermark
    backfill_cursor        timestamptz,            -- rückwärts laufender Backfill
    backfill_complete_to   timestamptz,
    sync_token             text,                   -- Google syncToken / CalDAV ctag
    last_run_at            timestamptz,
    last_success_at        timestamptz,
    consecutive_failures   smallint NOT NULL DEFAULT 0,
    PRIMARY KEY (user_id, connector, kind)
);

CREATE TABLE sync_failure (
    id           bigserial PRIMARY KEY,
    user_id      uuid NOT NULL REFERENCES app_user(id) ON DELETE CASCADE,
    connector    text NOT NULL,
    kind         text NOT NULL,
    window_start timestamptz,
    window_end   timestamptz,
    error        text NOT NULL,
    occurred_at  timestamptz NOT NULL DEFAULT now(),
    retry_after  timestamptz,
    resolved_at  timestamptz
);

CREATE TABLE audit_log (
    id          bigserial PRIMARY KEY,
    user_id     uuid REFERENCES app_user(id) ON DELETE SET NULL,
    actor       text NOT NULL,                     -- 'user' | 'agent' | 'system'
    action      text NOT NULL,
    target      text,
    detail      jsonb,
    result      text,
    occurred_at timestamptz NOT NULL DEFAULT now()
);

-- ---------------------------------------------------------------------
-- HEALTH: Stammdaten
-- ---------------------------------------------------------------------

-- Neue Wellness-Metriken sind ein INSERT hier, KEINE Migration.
CREATE TABLE metric_def (
    id          smallint PRIMARY KEY,
    key         text NOT NULL UNIQUE,   -- 'hr','stress','body_battery','spo2','respiration'
    unit        text NOT NULL,
    label_de    text NOT NULL,
    min_valid   real,
    max_valid   real,
    aggregation text NOT NULL DEFAULT 'mean'
                CHECK (aggregation IN ('mean','sum','min','max','last'))
);

CREATE TABLE data_source (
    id    smallint PRIMARY KEY,
    key   text NOT NULL UNIQUE          -- 'garmin','manual','apple_health','oura'
);

-- ---------------------------------------------------------------------
-- HEALTH: Zeitreihen (Narrow-Schema, Hypertable)
-- ---------------------------------------------------------------------

CREATE TABLE wellness_sample (
    user_id    uuid     NOT NULL,
    ts         timestamptz NOT NULL,
    metric_id  smallint NOT NULL REFERENCES metric_def(id),
    source_id  smallint NOT NULL REFERENCES data_source(id),
    value      real     NOT NULL,
    quality    smallint NOT NULL DEFAULT 0,   -- 0=ok 1=partial 2=suspect
    PRIMARY KEY (user_id, metric_id, source_id, ts)
);

SELECT create_hypertable('wellness_sample', 'ts',
                         chunk_time_interval => INTERVAL '7 days');

ALTER TABLE wellness_sample SET (
    timescaledb.compress,
    timescaledb.compress_segmentby = 'user_id, metric_id, source_id',
    timescaledb.compress_orderby   = 'ts'
);
SELECT add_compression_policy('wellness_sample', INTERVAL '7 days');

-- ---------------------------------------------------------------------
-- HEALTH: Aktivitäten
-- ---------------------------------------------------------------------

CREATE TABLE activity (
    id                uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id           uuid NOT NULL REFERENCES app_user(id) ON DELETE CASCADE,
    source_id         smallint NOT NULL REFERENCES data_source(id),
    external_id       text NOT NULL,
    sport             text NOT NULL,          -- 'running','cycling','strength',...
    sub_sport         text,
    started_at        timestamptz NOT NULL,
    local_timezone    text NOT NULL,
    duration_s        integer NOT NULL,
    moving_s          integer,
    distance_m        real,
    elevation_gain_m  real,
    hr_avg            smallint,
    hr_max            smallint,
    cadence_avg       real,
    power_avg         real,
    calories          integer,
    trimp             real,
    perceived_effort  smallint,               -- manuell nachtragbar (RPE 1-10)
    notes             text,
    has_records       boolean NOT NULL DEFAULT false,
    fit_object_key    text,
    extensions        jsonb NOT NULL DEFAULT '{}',
    ingested_at       timestamptz NOT NULL DEFAULT now(),
    UNIQUE (user_id, source_id, external_id)
);
CREATE INDEX ON activity (user_id, started_at DESC);
CREATE INDEX ON activity (user_id, sport, started_at DESC);

-- Sekundendaten: Wide-Schema, weil stabiles Feldset und gemeinsam gelesen
CREATE TABLE activity_record (
    user_id      uuid NOT NULL,
    activity_id  uuid NOT NULL,
    ts           timestamptz NOT NULL,
    hr           smallint,
    cadence      real,
    speed_ms     real,
    altitude_m   real,
    power_w      real,
    temperature  real,
    lat          double precision,
    lon          double precision,
    PRIMARY KEY (user_id, activity_id, ts)
);
SELECT create_hypertable('activity_record', 'ts',
                         chunk_time_interval => INTERVAL '30 days');
ALTER TABLE activity_record SET (
    timescaledb.compress,
    timescaledb.compress_segmentby = 'user_id, activity_id',
    timescaledb.compress_orderby   = 'ts'
);
SELECT add_compression_policy('activity_record', INTERVAL '1 day');

-- ---------------------------------------------------------------------
-- HEALTH: Schlaf & Tagesbilanz
-- ---------------------------------------------------------------------

CREATE TABLE sleep_session (
    user_id        uuid NOT NULL REFERENCES app_user(id) ON DELETE CASCADE,
    wake_date      date NOT NULL,       -- Konvention: Zuordnung zum AUFWACHTAG
    source_id      smallint NOT NULL REFERENCES data_source(id),
    sleep_start    timestamptz NOT NULL,
    sleep_end      timestamptz NOT NULL,
    total_s        integer NOT NULL,
    deep_s         integer,
    light_s        integer,
    rem_s          integer,
    awake_s        integer,
    score          smallint,
    hrv_avg_ms     real,
    hr_min         smallint,
    respiration_avg real,
    spo2_avg       real,
    levels         jsonb,               -- Phasen-Events, klein genug für JSONB
    quality        smallint NOT NULL DEFAULT 0,
    PRIMARY KEY (user_id, wake_date, source_id)
);

CREATE TABLE body_composition (
    user_id     uuid NOT NULL REFERENCES app_user(id) ON DELETE CASCADE,
    measured_at timestamptz NOT NULL,
    source_id   smallint NOT NULL REFERENCES data_source(id),
    weight_kg   real,
    body_fat_pct real,
    muscle_kg   real,
    water_pct   real,
    bone_kg     real,
    PRIMARY KEY (user_id, measured_at, source_id)
);

-- ---------------------------------------------------------------------
-- DERIVED: die Tabelle, aus der fast alle Agent-Antworten kommen
-- ---------------------------------------------------------------------

CREATE TABLE metric_daily (
    user_id           uuid NOT NULL REFERENCES app_user(id) ON DELETE CASCADE,
    day               date NOT NULL,
    hr_rest           smallint,
    hrv_night_ms      real,
    hrv_baseline_ms   real,
    hrv_baseline_sd   real,
    sleep_total_s     integer,
    sleep_score       smallint,
    sleep_debt_s      integer,
    stress_avg        real,
    bb_min            smallint,
    bb_max            smallint,
    steps             integer,
    active_kcal       integer,
    trimp             real,
    ctl               real,        -- chronische Belastung (Fitness)
    atl               real,        -- akute Belastung (Ermuedung)
    tsb               real,        -- Form = ctl - atl
    acwr              real,        -- acute:chronic workload ratio
    monotony          real,
    strain            real,
    coverage          real NOT NULL DEFAULT 1.0,  -- Anteil vorhandener Quelldaten
    computed_at       timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (user_id, day)
);

CREATE TABLE hr_zone_daily (
    user_id uuid NOT NULL REFERENCES app_user(id) ON DELETE CASCADE,
    day     date NOT NULL,
    zone    smallint NOT NULL CHECK (zone BETWEEN 1 AND 5),
    seconds integer NOT NULL,
    PRIMARY KEY (user_id, day, zone)
);

-- ---------------------------------------------------------------------
-- CALENDAR
-- ---------------------------------------------------------------------

CREATE TABLE calendar_account (
    id             uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    connection_id  uuid NOT NULL REFERENCES connection(id) ON DELETE CASCADE,
    user_id        uuid NOT NULL REFERENCES app_user(id) ON DELETE CASCADE,
    external_id    text NOT NULL,
    name           text NOT NULL,
    is_primary_write boolean NOT NULL DEFAULT false,
    read_only      boolean NOT NULL DEFAULT true,
    timezone       text,
    UNIQUE (connection_id, external_id)
);

-- Genau ein Schreibkalender pro Nutzer
CREATE UNIQUE INDEX one_write_calendar_per_user
    ON calendar_account (user_id) WHERE is_primary_write;

CREATE TABLE calendar_event (
    id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id       uuid NOT NULL REFERENCES app_user(id) ON DELETE CASCADE,
    account_id    uuid NOT NULL REFERENCES calendar_account(id) ON DELETE CASCADE,
    external_id   text NOT NULL,
    etag          text,
    sequence      integer,
    title         text,
    description   text,
    location      text,
    starts_at     timestamptz NOT NULL,
    ends_at       timestamptz NOT NULL,
    all_day       boolean NOT NULL DEFAULT false,
    timezone      text,
    status        text,
    transparency  text,                 -- 'opaque' = belegt, 'transparent' = frei
    recurrence    jsonb,
    origin        text NOT NULL DEFAULT 'external'
                  CHECK (origin IN ('external','kairos')),
    plan_block_id uuid,                 -- gesetzt, wenn von Kairos erzeugt
    dedup_group   uuid,                 -- gespiegelte Events ueber Konten hinweg
    updated_at    timestamptz NOT NULL DEFAULT now(),
    UNIQUE (account_id, external_id)
);
CREATE INDEX ON calendar_event (user_id, starts_at);

-- ---------------------------------------------------------------------
-- PLANNING
-- ---------------------------------------------------------------------

CREATE TABLE goal (
    id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id     uuid NOT NULL REFERENCES app_user(id) ON DELETE CASCADE,
    kind        text NOT NULL,          -- 'race','habit','learning','weight'
    title       text NOT NULL,
    target_date date,
    spec        jsonb NOT NULL DEFAULT '{}',
    active      boolean NOT NULL DEFAULT true,
    created_at  timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE plan (
    id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id     uuid NOT NULL REFERENCES app_user(id) ON DELETE CASCADE,
    goal_id     uuid REFERENCES goal(id) ON DELETE SET NULL,
    title       text NOT NULL,
    starts_on   date NOT NULL,
    ends_on     date NOT NULL,
    status      text NOT NULL DEFAULT 'active'
                CHECK (status IN ('draft','active','completed','abandoned')),
    created_at  timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE plan_block (
    id           uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    plan_id      uuid NOT NULL REFERENCES plan(id) ON DELETE CASCADE,
    user_id      uuid NOT NULL REFERENCES app_user(id) ON DELETE CASCADE,
    kind         text NOT NULL,         -- 'training','learning','recovery','other'
    title        text NOT NULL,
    planned_start timestamptz NOT NULL,
    planned_end   timestamptz NOT NULL,
    spec         jsonb NOT NULL DEFAULT '{}',   -- z.B. Zieldauer, Zone, Intervalle
    status       text NOT NULL DEFAULT 'planned'
                 CHECK (status IN ('planned','done','skipped','moved')),
    activity_id  uuid REFERENCES activity(id) ON DELETE SET NULL,  -- Ist-Abgleich
    calendar_event_id uuid REFERENCES calendar_event(id) ON DELETE SET NULL
);
CREATE INDEX ON plan_block (user_id, planned_start);

-- Vorgeschlagene, noch nicht ausgefuehrte Schreibaktion
CREATE TABLE proposal (
    id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id         uuid NOT NULL REFERENCES app_user(id) ON DELETE CASCADE,
    conversation_id uuid,
    tool_id         text NOT NULL,
    risk_class      text NOT NULL CHECK (risk_class IN ('write','destructive')),
    payload         jsonb NOT NULL,
    human_summary   text NOT NULL,
    idempotency_key text NOT NULL UNIQUE,
    status          text NOT NULL DEFAULT 'pending'
                    CHECK (status IN ('pending','confirmed','executed',
                                      'rejected','expired','failed')),
    created_at      timestamptz NOT NULL DEFAULT now(),
    expires_at      timestamptz NOT NULL DEFAULT now() + INTERVAL '1 hour',
    resolved_at     timestamptz,
    result          jsonb
);

-- ---------------------------------------------------------------------
-- AGENT
-- ---------------------------------------------------------------------

CREATE TABLE conversation (
    id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id     uuid NOT NULL REFERENCES app_user(id) ON DELETE CASCADE,
    title       text,
    summary     text,                   -- Rolling Compaction
    summary_embedding vector(1024),
    started_at  timestamptz NOT NULL DEFAULT now(),
    last_at     timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE message (
    id              bigserial PRIMARY KEY,
    conversation_id uuid NOT NULL REFERENCES conversation(id) ON DELETE CASCADE,
    user_id         uuid NOT NULL REFERENCES app_user(id) ON DELETE CASCADE,
    role            text NOT NULL CHECK (role IN ('user','assistant','tool')),
    content         jsonb NOT NULL,
    tool_id         text,
    input_tokens    integer,
    output_tokens   integer,
    model           text,
    created_at      timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX ON message (conversation_id, created_at);

CREATE TABLE memory (
    id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id     uuid NOT NULL REFERENCES app_user(id) ON DELETE CASCADE,
    kind        text NOT NULL CHECK (kind IN ('profile','semantic','episodic')),
    content     text NOT NULL,
    embedding   vector(1024),
    status      text NOT NULL DEFAULT 'active'
                CHECK (status IN ('proposed','active','archived')),
    source      text,                   -- 'explicit' | 'extracted'
    valid_from  date,
    valid_until date,                   -- z.B. abgelaufene Verletzung
    created_at  timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX ON memory USING hnsw (embedding vector_cosine_ops);

CREATE TABLE tool_registry (
    tool_id     text PRIMARY KEY,
    name        text NOT NULL,
    pack        text NOT NULL,
    version     text NOT NULL,
    plugin_id   text,
    one_liner   text NOT NULL,          -- ~15 Tokens, Rueckgabe von search_tools
    when_to_use text NOT NULL,          -- 2 Saetze
    json_schema jsonb NOT NULL,         -- nur bei load_tools in den Kontext
    embedding   vector(1024),
    risk_class  text NOT NULL DEFAULT 'read'
                CHECK (risk_class IN ('read','write','destructive')),
    mcp_server  text,
    is_core     boolean NOT NULL DEFAULT false,
    enabled     boolean NOT NULL DEFAULT true
);
CREATE INDEX ON tool_registry USING hnsw (embedding vector_cosine_ops);

CREATE TABLE tool_usage (
    user_id     uuid NOT NULL REFERENCES app_user(id) ON DELETE CASCADE,
    tool_id     text NOT NULL REFERENCES tool_registry(tool_id) ON DELETE CASCADE,
    call_count  integer NOT NULL DEFAULT 0,
    last_used   timestamptz,
    PRIMARY KEY (user_id, tool_id)
);

-- ---------------------------------------------------------------------
-- DASHBOARD-MODULE
-- ---------------------------------------------------------------------

CREATE TABLE module_registry (
    module_id           text PRIMARY KEY,
    plugin_id           text,
    definition          jsonb NOT NULL,
    requires_capability text,
    enabled             boolean NOT NULL DEFAULT true
);

CREATE TABLE user_dashboard (
    user_id   uuid NOT NULL REFERENCES app_user(id) ON DELETE CASCADE,
    module_id text NOT NULL REFERENCES module_registry(module_id) ON DELETE CASCADE,
    position  smallint NOT NULL,
    config    jsonb NOT NULL DEFAULT '{}',
    PRIMARY KEY (user_id, module_id)
);

-- ---------------------------------------------------------------------
-- ROW LEVEL SECURITY
--
-- Fuer jede Tabelle mit user_id. Die Anwendung setzt pro Transaktion
--   SET LOCAL app.current_user_id = '<uuid>';
-- Ein vergessener WHERE-Filter liefert damit 0 Zeilen statt fremder Daten.
-- Ein CI-Test prueft, dass keine fachliche Tabelle ohne Policy existiert.
-- ---------------------------------------------------------------------

DO $$
DECLARE t text;
BEGIN
  FOREACH t IN ARRAY ARRAY[
    'user_setting','connection','raw_payload','sync_state','sync_failure',
    'wellness_sample','activity','activity_record','sleep_session',
    'body_composition','metric_daily','hr_zone_daily',
    'calendar_account','calendar_event','goal','plan','plan_block','proposal',
    'conversation','message','memory','tool_usage','user_dashboard'
  ] LOOP
    EXECUTE format('ALTER TABLE %I ENABLE ROW LEVEL SECURITY', t);
    EXECUTE format('ALTER TABLE %I FORCE  ROW LEVEL SECURITY', t);
    EXECUTE format($f$
      CREATE POLICY tenant_isolation ON %I
        USING      (user_id = current_setting('app.current_user_id', true)::uuid)
        WITH CHECK (user_id = current_setting('app.current_user_id', true)::uuid)
    $f$, t);
  END LOOP;
END $$;

-- ---------------------------------------------------------------------
-- SEED
-- ---------------------------------------------------------------------

INSERT INTO data_source (id, key) VALUES
  (1,'garmin'), (2,'manual'), (3,'apple_health'), (4,'derived');

INSERT INTO metric_def (id, key, unit, label_de, min_valid, max_valid, aggregation) VALUES
  (1,'hr','bpm','Herzfrequenz',25,230,'mean'),
  (2,'stress','score','Stress-Level',0,100,'mean'),
  (3,'body_battery','score','Body Battery',0,100,'last'),
  (4,'spo2','%','Sauerstoffsaettigung',70,100,'mean'),
  (5,'respiration','brpm','Atemfrequenz',4,40,'mean'),
  (6,'steps','count','Schritte',0,100000,'sum'),
  (7,'hrv','ms','Herzratenvariabilitaet',5,250,'mean');
