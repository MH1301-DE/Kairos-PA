import type { Actions, PageServerLoad } from './$types';
import { redirect, fail } from '@sveltejs/kit';
import { apiDelete, apiGet, apiPatch, apiPost, ApiError } from '$lib/api';
import type { MemoryEntry } from '$lib/types';

export const load: PageServerLoad = async ({ fetch, depends }) => {
	depends('memory:list');
	try {
		const { entries } = await apiGet<{ entries: MemoryEntry[] }>(fetch, '/api/memory');
		return { entries };
	} catch (err) {
		if (err instanceof ApiError && err.status === 401) redirect(302, '/auth/login');
		throw err;
	}
};

export const actions: Actions = {
	create: async ({ request, fetch }) => {
		const form = await request.formData();
		const content = (form.get('content') as string)?.trim();
		if (!content) {
			return fail(422, { createError: 'Text darf nicht leer sein.' });
		}
		const { status, data } = await apiPost<{ detail?: string }>(fetch, '/api/memory', { content });
		if (status !== 201) {
			return fail(status, {
				createError: `Eintrag konnte nicht gespeichert werden (${status}): ${data.detail ?? 'unbekannt'}`
			});
		}
		return { created: true };
	},
	update: async ({ request, fetch }) => {
		const form = await request.formData();
		const memoryId = form.get('memory_id') as string;
		const content = (form.get('content') as string)?.trim();
		if (!content) {
			return fail(422, { updateError: 'Text darf nicht leer sein.' });
		}
		const { status, data } = await apiPatch<{ detail?: string }>(fetch, `/api/memory/${memoryId}`, {
			content
		});
		if (status !== 200) {
			return fail(status, {
				updateError: `Eintrag konnte nicht geändert werden (${status}): ${data.detail ?? 'unbekannt'}`
			});
		}
		return { updated: true };
	},
	remove: async ({ request, fetch }) => {
		const form = await request.formData();
		const memoryId = form.get('memory_id') as string;
		const { status, data } = await apiDelete<{ detail?: string }>(fetch, `/api/memory/${memoryId}`);
		if (status !== 204) {
			return fail(status, {
				deleteError: `Eintrag konnte nicht gelöscht werden (${status}): ${data.detail ?? 'unbekannt'}`
			});
		}
		return { deleted: true };
	}
};
