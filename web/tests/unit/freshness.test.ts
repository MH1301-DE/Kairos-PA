import { describe, expect, it } from 'vitest';
import { freshness } from '../../src/lib/design/freshness';
import type { ConnectionInfo, SyncJob } from '../../src/lib/types';

const NOW = new Date('2026-10-05T12:00:00Z');

function conn(overrides: Partial<ConnectionInfo> = {}): ConnectionInfo {
	return {
		connector: 'garmin',
		status: 'active',
		external_account: 'a@b.de',
		connected_at: '2026-09-01T00:00:00Z',
		last_ok_at: '2026-10-05T10:30:00Z',
		token_refreshed_at: null,
		reauth_since: null,
		...overrides
	};
}

function job(overrides: Partial<SyncJob> = {}): SyncJob {
	return {
		job_id: 'j1',
		connector: 'garmin',
		kind: 'sleep',
		from_date: '2026-10-01',
		to_date: '2026-10-05',
		status: 'running',
		windows_processed: 2,
		windows_total: 4,
		error: null,
		started_at: '2026-10-05T11:59:00Z',
		finished_at: null,
		...overrides
	};
}

describe('freshness', () => {
	it('returns null without a garmin connection', () => {
		expect(freshness(undefined, [], NOW)).toBeNull();
	});

	it('is "expired" when garmin needs a new login, even while jobs run', () => {
		const f = freshness(conn({ status: 'reauth_required' }), [job()], NOW);
		expect(f?.state).toBe('abgelaufen');
	});

	it('is "syncing" with progress while a garmin job runs', () => {
		const f = freshness(conn(), [job(), job({ job_id: 'j2', connector: 'google_calendar' })], NOW);
		expect(f).toMatchObject({ state: 'laeuft', label: 'Abgleich läuft · 2 von 4' });
	});

	it('sums progress over all running garmin jobs', () => {
		const jobs = [job(), job({ job_id: 'j2', windows_processed: 1, windows_total: 3 })];
		expect(freshness(conn(), jobs, NOW)?.label).toBe('Abgleich läuft · 3 von 7');
	});

	it('is "current" within six hours', () => {
		const f = freshness(conn(), [job({ status: 'done' })], NOW);
		expect(f?.state).toBe('aktuell');
		expect(f?.label).toMatch(/^aktuell · \d\d:\d\d$/);
	});

	it('is "stale" after six hours and names the day', () => {
		const f = freshness(conn({ last_ok_at: '2026-10-04T20:10:00Z' }), [], NOW);
		expect(f?.state).toBe('veraltet');
		expect(f?.label).toMatch(/^Garmin-Stand von gestern, \d\d:\d\d$/);
	});

	it('is "stale" when garmin never synced', () => {
		expect(freshness(conn({ last_ok_at: null }), [], NOW)?.state).toBe('veraltet');
	});
});
