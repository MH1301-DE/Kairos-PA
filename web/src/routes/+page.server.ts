import type { Actions, PageServerLoad } from './$types';
import { redirect } from '@sveltejs/kit';
import { apiGet, apiPost, ApiError } from '$lib/api';
import { MODULES } from '$lib/modules';
import type { MetricResult } from '$lib/types';

export const load: PageServerLoad = async ({ fetch, depends }) => {
	depends('dashboard:tiles');
	try {
		const results = await Promise.all(
			MODULES.map(async (m) => {
				try {
					const result = await apiGet<MetricResult>(
						fetch,
						`/api/metrics/${m.moduleId}?variant=${m.variant}`
					);
					return { moduleId: m.moduleId, result, error: null as string | null };
				} catch (err) {
					// a stale session 401s every tile — escalate instead of masking it as missing data
					if (err instanceof ApiError && err.status === 401) throw err;
					return {
						moduleId: m.moduleId,
						result: null as MetricResult | null,
						error: 'Daten gerade nicht verfügbar'
					};
				}
			})
		);
		return { tiles: results };
	} catch (err) {
		if (err instanceof ApiError && err.status === 401) redirect(302, '/auth/login');
		throw err;
	}
};

// Also handles the top-right account menu's trigger buttons -- SvelteKit form
// actions only exist on +page.server.ts, never +layout.server.ts, so these
// live here (the dashboard) even though the menu itself renders in the
// layout; the menu's forms point their `action` at "/?/..." explicitly.
export const actions: Actions = {
	triggerGarminBackfill: async ({ fetch }) => {
		const { status, data } = await apiPost<{ detail?: string }>(
			fetch,
			'/api/sync/garmin/backfill',
			{}
		);
		if (status !== 202) {
			return {
				menuError: `Backfill konnte nicht gestartet werden (${status}): ${data.detail ?? 'unbekannt'}`
			};
		}
		return { menuTriggered: 'garmin' };
	},
	triggerCalendarSync: async ({ fetch }) => {
		const { status, data } = await apiPost<{ detail?: string }>(
			fetch,
			'/api/sync/google_calendar/sync',
			{}
		);
		if (status !== 202) {
			return {
				menuError: `Kalender-Sync konnte nicht gestartet werden (${status}): ${data.detail ?? 'unbekannt'}`
			};
		}
		return { menuTriggered: 'calendar' };
	}
};
