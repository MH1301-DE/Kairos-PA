import type { Actions, PageServerLoad } from './$types';
import { redirect } from '@sveltejs/kit';
import { apiDelete, apiGet, apiPatch, apiPost, ApiError } from '$lib/api';
import type { Goal } from '$lib/types';

export const load: PageServerLoad = async ({ fetch, depends }) => {
	depends('goals:list');
	try {
		const { goals } = await apiGet<{ goals: Goal[] }>(fetch, '/api/goals');
		return { goals };
	} catch (err) {
		if (err instanceof ApiError && err.status === 401) redirect(302, '/auth/login');
		throw err;
	}
};

export const actions: Actions = {
	create: async ({ request, fetch }) => {
		const form = await request.formData();
		const title = (form.get('title') as string)?.trim();
		if (!title) {
			return { createError: 'Titel ist erforderlich.' };
		}
		const targetValueRaw = form.get('target_value') as string;
		const targetDateRaw = form.get('target_date') as string;
		const targetUnit = (form.get('target_unit') as string) || null;
		const notes = (form.get('notes') as string) || null;

		const { status, data } = await apiPost<{ detail?: string }>(fetch, '/api/goals', {
			title,
			target_value: targetValueRaw ? Number(targetValueRaw) : null,
			target_unit: targetUnit,
			target_date: targetDateRaw || null,
			notes
		});
		if (status !== 201) {
			return { createError: `Ziel konnte nicht angelegt werden (${status}): ${data.detail ?? 'unbekannt'}` };
		}
		return { created: true };
	},
	updateStatus: async ({ request, fetch }) => {
		const form = await request.formData();
		const goalId = form.get('goal_id') as string;
		const status = form.get('status') as string;
		const { status: respStatus, data } = await apiPatch<{ detail?: string }>(
			fetch,
			`/api/goals/${goalId}`,
			{ status }
		);
		if (respStatus !== 200) {
			return { updateError: `Status konnte nicht geändert werden (${respStatus}): ${data.detail ?? 'unbekannt'}` };
		}
		return { updated: true };
	},
	remove: async ({ request, fetch }) => {
		const form = await request.formData();
		const goalId = form.get('goal_id') as string;
		const { status, data } = await apiDelete<{ detail?: string }>(fetch, `/api/goals/${goalId}`);
		if (status !== 204) {
			return { deleteError: `Ziel konnte nicht gelöscht werden (${status}): ${data.detail ?? 'unbekannt'}` };
		}
		return { deleted: true };
	}
};
