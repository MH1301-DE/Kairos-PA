// web/src/routes/sync/+page.server.ts
import type { Actions, PageServerLoad } from './$types';
import { redirect } from '@sveltejs/kit';
import { apiGet, apiPost, ApiError } from '$lib/api';
import type { ConnectionInfo, SyncJob } from '$lib/types';

export const load: PageServerLoad = async ({ fetch, depends }) => {
	depends('sync:status');
	try {
		const [connections, syncStatus] = await Promise.all([
			apiGet<{ connections: ConnectionInfo[] }>(fetch, '/api/connections'),
			apiGet<{ jobs: SyncJob[] }>(fetch, '/api/sync/status')
		]);
		return { connections: connections.connections, jobs: syncStatus.jobs };
	} catch (err) {
		// stale/invalid session cookie: send the user back to login instead of a dead end
		if (err instanceof ApiError && err.status === 401) redirect(302, '/auth/login');
		throw err;
	}
};

export const actions: Actions = {
	triggerBackfill: async ({ fetch }) => {
		const { status, data } = await apiPost<{ detail?: string }>(
			fetch,
			'/api/sync/garmin/backfill',
			{}
		);
		if (status !== 202) {
			return { triggerError: `Backfill konnte nicht gestartet werden (${status}): ${data.detail ?? 'unbekannt'}` };
		}
		return { triggered: 'garmin' };
	},
	triggerCalendarSync: async ({ fetch }) => {
		const { status, data } = await apiPost<{ detail?: string }>(
			fetch,
			'/api/sync/google_calendar/sync',
			{}
		);
		if (status !== 202) {
			return {
				triggerError: `Kalender-Sync konnte nicht gestartet werden (${status}): ${data.detail ?? 'unbekannt'}`
			};
		}
		return { triggered: 'calendar' };
	}
};
