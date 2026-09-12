import type { Actions, PageServerLoad } from './$types';
import { redirect, fail } from '@sveltejs/kit';
import { apiGet, apiPut, ApiError } from '$lib/api';
import { MODULES } from '$lib/modules';
import type { DashboardTileLayout, MetricResult } from '$lib/types';

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
		const { tiles: layout } = await apiGet<{ tiles: DashboardTileLayout[] }>(
			fetch,
			'/api/dashboard/layout'
		);
		return { tiles: results, layout };
	} catch (err) {
		if (err instanceof ApiError && err.status === 401) redirect(302, '/auth/login');
		throw err;
	}
};

export const actions: Actions = {
	saveLayout: async ({ request, fetch }) => {
		const form = await request.formData();
		const raw = String(form.get('layout') ?? '[]');
		let tiles: DashboardTileLayout[];
		try {
			tiles = JSON.parse(raw);
		} catch {
			return fail(400, { layoutError: 'Ungültiges Layout.' });
		}
		const { status, data } = await apiPut<{ detail?: string }>(
			fetch,
			'/api/dashboard/layout',
			{ tiles }
		);
		if (status === 401) redirect(302, '/auth/login');
		if (status !== 200) {
			return fail(status, {
				layoutError: `Layout konnte nicht gespeichert werden (${status}): ${data.detail ?? 'unbekannt'}`
			});
		}
		return { layoutSaved: true };
	}
};
