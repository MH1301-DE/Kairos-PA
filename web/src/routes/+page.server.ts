import type { PageServerLoad } from './$types';
import { apiGet } from '$lib/api';
import { MODULES } from '$lib/modules';
import type { MetricResult } from '$lib/types';

export const load: PageServerLoad = async ({ fetch }) => {
	const results = await Promise.all(
		MODULES.map(async (m) => {
			try {
				const result = await apiGet<MetricResult>(
					fetch,
					`/api/metrics/${m.moduleId}?variant=${m.variant}`
				);
				return { moduleId: m.moduleId, result, error: null as string | null };
			} catch {
				return {
					moduleId: m.moduleId,
					result: null as MetricResult | null,
					error: 'Daten gerade nicht verfügbar'
				};
			}
		})
	);
	return { tiles: results };
};
