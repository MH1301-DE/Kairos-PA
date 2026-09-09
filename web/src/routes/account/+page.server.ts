// web/src/routes/account/+page.server.ts
import type { PageServerLoad } from './$types';
import { redirect } from '@sveltejs/kit';
import { apiGet, ApiError } from '$lib/api';
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
