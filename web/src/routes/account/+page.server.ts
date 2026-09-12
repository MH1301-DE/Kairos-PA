// web/src/routes/account/+page.server.ts
import type { Actions, PageServerLoad } from './$types';
import { redirect, fail } from '@sveltejs/kit';
import { apiGet, apiPost, ApiError } from '$lib/api';
import type { ConnectionInfo } from '$lib/types';

export const load: PageServerLoad = async ({ fetch, depends }) => {
	depends('account:connections');
	try {
		const { connections } = await apiGet<{ connections: ConnectionInfo[] }>(
			fetch,
			'/api/connections'
		);
		return { connections };
	} catch (err) {
		if (err instanceof ApiError && err.status === 401) redirect(302, '/auth/login');
		throw err;
	}
};

export const actions: Actions = {
	connectLlm: async ({ request, fetch }) => {
		const form = await request.formData();
		const model = String(form.get('model') ?? '').trim();
		const apiKey = String(form.get('api_key') ?? '').trim();
		if (!model || !apiKey) {
			return fail(400, { llmError: 'Modell und API-Key sind erforderlich.' });
		}
		const { status, data } = await apiPost<{ detail?: string }>(
			fetch,
			'/api/connections/llm_provider',
			{ model, api_key: apiKey }
		);
		if (status === 401) redirect(302, '/auth/login');
		if (status !== 201) {
			return fail(status, {
				llmError: `Verbindung fehlgeschlagen (${status}): ${data.detail ?? 'unbekannt'}`
			});
		}
		return { llmSuccess: true };
	}
};
