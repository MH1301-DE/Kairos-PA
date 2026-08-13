// web/src/routes/calendar/+page.server.ts
import type { PageServerLoad, Actions } from './$types';
import { apiGet, apiPost, ApiError } from '$lib/api';
import { redirect, fail } from '@sveltejs/kit';
import type { CalendarEvent, FreeSlot } from '$lib/types';

function _range(): { from: string; to: string } {
	const from = new Date();
	const to = new Date(from.getTime() + 14 * 24 * 60 * 60 * 1000);
	return { from: from.toISOString().slice(0, 10), to: to.toISOString().slice(0, 10) };
}

export const load: PageServerLoad = async ({ fetch }) => {
	const { from, to } = _range();
	try {
		const events = await apiGet<{ events: CalendarEvent[] }>(
			fetch,
			`/api/calendar/events?from=${from}&to=${to}`
		);
		return { events: events.events, from, to };
	} catch (err) {
		// stale/invalid session cookie: send the user back to login instead of a dead end
		if (err instanceof ApiError && err.status === 401) redirect(302, '/auth/login');
		throw err;
	}
};

export const actions: Actions = {
	'propose-slots': async ({ request, fetch }) => {
		const form = await request.formData();
		const durationMinutes = Number(form.get('duration_minutes'));
		const { from, to } = _range();
		try {
			const result = await apiGet<{ slots: FreeSlot[] }>(
				fetch,
				`/api/calendar/free-slots?from=${from}&to=${to}&duration_minutes=${durationMinutes}`
			);
			return { slots: result.slots, durationMinutes };
		} catch (err) {
			if (err instanceof ApiError && err.status === 401) redirect(302, '/auth/login');
			return fail(500, { error: 'Freie Zeitfenster konnten nicht geladen werden.' });
		}
	},
	confirm: async ({ request, fetch }) => {
		const form = await request.formData();
		const summary = String(form.get('summary'));
		const start_at = String(form.get('start_at'));
		const end_at = String(form.get('end_at'));
		const { status, data } = await apiPost<{ detail?: string }>(fetch, '/api/calendar/events', {
			summary,
			start_at,
			end_at,
			description: null
		});
		if (status !== 201) {
			return fail(status, {
				error: `Termin konnte nicht angelegt werden (${data.detail ?? status}).`
			});
		}
		return { confirmed: true };
	},
	delete: async ({ request, fetch }) => {
		const form = await request.formData();
		const eventId = String(form.get('event_id'));
		const resp = await fetch(`/api/calendar/events/${eventId}`, {
			method: 'DELETE',
			credentials: 'include'
		});
		if (!resp.ok) {
			if (resp.status === 401) redirect(302, '/auth/login');
			return fail(resp.status, { error: 'Termin konnte nicht gelöscht werden.' });
		}
		return { deleted: true };
	},
	sync: async ({ fetch }) => {
		const { status } = await apiPost(fetch, '/api/sync/google_calendar/sync', {});
		if (status === 401) redirect(302, '/auth/login');
		if (status !== 202) {
			return fail(status, { error: 'Synchronisierung konnte nicht gestartet werden.' });
		}
		return { syncStarted: true };
	}
};
