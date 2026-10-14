# Activity regression fixtures (spec §12.3, Q5)

Four real activities of the developer account, decoded and anonymized, for the derivation
regression tests (Teil B). No FIT file is stored, only the decoded messages the derivations need.

| File | Content | Used for |
|---|---|---|
| `run_autolap_1km_9k.json.gz` | outdoor run, 9.0 km, Auto-Lap 1 km, 10 laps | V1 (km splits vs. laps), V5, V6 |
| `run_workout_threshold_4x6.json.gz` | outdoor run, workout "W3 Do Schwelle 4x6", 16 laps, pauses | laps with `wkt_step_index`, B.6 / V7 |
| `swim_pool_1000m.json.gz` | pool swim 1000 m, 50 m pool, 27 lengths, HR only stream | 100 m splits from lengths, `quality='partial'` |
| `run_treadmill_intervals_7k.json.gz` | treadmill intervals 7.3 km, no GPS, workout | `distance_source='watch_estimate'` |

Load them in tests with `tests/activity_fixtures.py::load_activity_fixture(name)`, which returns
`ActivityFixture(stream: LoadedStream, messages, summary, list_item)` with datetimes restored.

## Schema (`schema_version` 1)

gzip-compressed UTF-8 JSON, one object:

```
{
  "schema_version": 1,
  "name": "<file stem>",
  "source_activity_id": <activity.id in the developer DB>,
  "activity": { <activity summary columns> },
  "activity_list_item": { <whitelisted fields of the raw Garmin activity_list item> },
  "stream": {
    "start_at": "<ISO 8601 UTC>",
    "source": "fit_zip",
    "t_offset_s": [int, ...],
    "channels": {"hr": [float|null, ...], "distance_m": [...], ...}
  },
  "messages": {
    "session_mesgs": [...], "lap_mesgs": [...], "length_mesgs": [...], "event_mesgs": [...],
    "split_mesgs": [...], "workout_mesgs": [...], "workout_step_mesgs": [...]
  }
}
```

- `stream` is exactly what `kairos.activities.stream_repository.load_stream` returned (all channels).
- `activity` holds the `activity` columns `sport, sport_profile, garmin_type_id, garmin_parent_type_id,
  start_at, end_at, start_local, utc_offset_min, moving_duration_s, avg_speed_mps, lap_count,
  garmin_training_load, garmin_vo2max, distance_m, duration_s, avg_hr, max_hr, elevation_gain_m,
  calories` (`start_at`/`end_at` ISO with offset, `start_local` naive ISO).
- `activity_list_item` keeps only summary values for the V comparisons, e.g. `distance`, `duration`,
  `movingDuration`, `averageHR`, `averageRunningCadenceInStepsPerMinute`, `elevationGain`,
  `elevationLoss`, `avgPower`, `poolLength`, `activeLengths`, `averageSwolf`, all `fastestSplit_*`
  and `hrTimeInZone_*`, and `activityType` reduced to `typeKey`, `typeId`, `parentTypeId`.
- `messages` are the decoded FIT messages (`decode_fit_zip`, as from `load_fit_messages`).
  Datetime fields (`timestamp`, `start_time`, `end_time`) are ISO 8601 strings; the loader turns
  them back into aware `datetime`s. Enum values stay as decoded (string, or int if unknown, e.g.
  `event: 39`).

## Anonymization

- GPS: `lat_deg`/`lng_deg` and all semicircle position fields (`*_lat`, `*_long`) are shifted by
  one fixed offset per export. The offset is a CLI argument of the export script and is not stored.
  Distances come from `distance_m`, so no derivation depends on absolute positions.
- Only the seven message kinds above are kept; `file_id`, `device_info`, `user_profile` (name,
  weight, height, birth year), `device_settings`, `gps_metadata` and every numeric-keyed
  (undocumented) message are dropped.
- Inside kept messages every numeric-keyed field and every field containing `serial` is dropped.
- No activity name, Garmin activity id, owner, device id or location name is stored; file names
  carry no place names.
- Kept on purpose: timestamps, workout name/notes, the physiological channels (they are the
  test subject).

## Regenerating

```
.venv/Scripts/python scripts/export_activity_fixture.py --user-id <uuid> --activity-id <id> \
    --name <file stem> --lat-offset <deg> --lng-offset <deg>
```

Read-only against the database (RLS session, rolled back). Source ids: 252, 272, 61, 22.
Regenerated files change test expectations; re-run the derivation tests.
