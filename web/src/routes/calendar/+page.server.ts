// web/src/routes/calendar/+page.server.ts
import type { PageServerLoad, Actions } from './$types';
import { apiGet, apiPost, ApiError } from '$lib/api';
import { redirect, fail } from '@sveltejs/kit';
import type { CalendarEvent, FreeSlot } from '$lib/types';
import { monthGridDays, nextDateKey } from '$lib/calendarGrid';

function parseMonth(searchParams: URLSearchParams): { year: number; month: number } {
	const param = searchParams.get('month'); // "YYYY-MM"
	if (param) {
		const match = /^(\d{4})-(\d{2})$/.exec(param);
		if (match) {
			const year = Number(match[1]);
			const month = Number(match[2]);
			if (month >= 1 && month <= 12) return { year, month };
		}
	}
	const now = new Date();
	return { year: now.getFullYear(), month: now.getMonth() + 1 };
}

export const load: PageServerLoad = async ({ fetch, url }) => {
	const { year, month } = parseMonth(url.searchParams);
	const days = monthGridDays(year, month);
	const from = days[0].date;
	// the API's `to` is exclusive (start_at < to) -- one day past the last grid day
	const to = nextDateKey(days[days.length - 1].date);
	try {
		const events = await apiGet<{ events: CalendarEvent[] }>(
			fetch,
			`/api/calendar/events?from=${from}&to=${to}`
		);
		return { events: events.events, year, month, gridFrom: from, gridTo: to };
	} catch (err) {
		// stale/invalid session cookie: send the user back to login instead of a dead end
		if (err instanceof ApiError && err.status === 401) redirect(302, '/auth/login');
		throw err;
	}
};

export const actions: Actions = {
	create: async ({ request, fetch }) => {
		const form = await request.formData();
		const summary = String(form.get('summary') ?? '').trim();
		const date = String(form.get('date') ?? '');
		const startTime = String(form.get('start_time') ?? '');
		const endTime = String(form.get('end_time') ?? '');
		const description = String(form.get('description') ?? '').trim() || null;

		if (!summary || !date || !startTime || !endTime) {
			return fail(400, { createError: 'Titel, Datum sowie Start- und Endzeit sind Pflicht.' });
		}
		const start_at = new Date(`${date}T${startTime}`).toISOString();
		const end_at = new Date(`${date}T${endTime}`).toISOString();
		if (end_at <= start_at) {
			return fail(400, { createError: 'Die Endzeit muss nach der Startzeit liegen.' });
		}

		const { status, data } = await apiPost<{ detail?: string }>(fetch, '/api/calendar/events', {
			summary,
			start_at,
			end_at,
			description
		});
		if (status === 401) redirect(302, '/auth/login');
		if (status !== 201) {
			return fail(status, {
				createError: `Termin konnte nicht angelegt werden (${data.detail ?? status}).`
			});
		}
		return { created: true };
	},
	'propose-slots': async ({ request, fetch, url }) => {
		const form = await request.formData();
		const durationMinutes = Number(form.get('duration_minutes'));
		const { year, month } = parseMonth(url.searchParams);
		const days = monthGridDays(year, month);
		const from = days[0].date;
		const to = nextDateKey(days[days.length - 1].date);
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
		// the confirm() dialog in +page.svelte already gated this for external
		// events before the form was submitted -- confirm=true here just carries
		// that decision through to the API, which enforces it independently
		const confirm = String(form.get('confirm') ?? 'false');
		const resp = await fetch(`/api/calendar/events/${eventId}?confirm=${confirm}`, {
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
