import type { Actions, PageServerLoad } from './$types';
import { fail, redirect } from '@sveltejs/kit';
import { apiGet, apiPut, ApiError } from '$lib/api';

const WEEKDAYS = ['mo', 'di', 'mi', 'do', 'fr', 'sa', 'so'] as const;

interface DayAvailability {
	max_min: number;
	quality: boolean;
	time?: string;
}

interface CoachProfileResponse {
	profile: {
		plan_type: string;
		main_sport: string;
		availability: Record<string, DayAvailability>;
		onboarded_at: string | null;
	} | null;
	plan_types: { id: string; titel: string; hauptsport: string }[];
}

export const load: PageServerLoad = async ({ fetch }) => {
	try {
		return { coach: await apiGet<CoachProfileResponse>(fetch, '/api/coach/profile') };
	} catch (err) {
		if (err instanceof ApiError && err.status === 401) redirect(302, '/auth/login');
		throw err;
	}
};

export const actions: Actions = {
	save: async ({ request, fetch }) => {
		const form = await request.formData();
		const availability: Record<string, DayAvailability> = {};
		for (const day of WEEKDAYS) {
			const minutes = Number(form.get(`${day}_max_min`) || 0);
			if (!Number.isFinite(minutes) || minutes < 0 || minutes > 600) {
				return fail(422, { saveError: 'Minuten pro Tag: 0–600.' });
			}
			if (minutes === 0) continue;
			const time = ((form.get(`${day}_time`) as string | null) ?? '').trim();
			availability[day] = {
				max_min: minutes,
				quality: form.get(`${day}_quality`) === 'on',
				...(time ? { time } : {})
			};
		}
		if (Object.keys(availability).length === 0) {
			return fail(422, { saveError: 'Mindestens ein Trainingstag mit Minuten > 0.' });
		}
		const { status } = await apiPut<{ detail?: unknown }>(fetch, '/api/coach/profile', {
			plan_type: form.get('plan_type'),
			availability
		});
		if (status === 401) redirect(302, '/auth/login');
		if (status !== 200) {
			return fail(status, { saveError: `Profil konnte nicht gespeichert werden (${status}).` });
		}
		return { saved: true };
	}
};
