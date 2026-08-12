// web/src/routes/sync/+page.server.ts
import type { PageServerLoad } from './$types';
import { apiGet } from '$lib/api';
import type { ConnectionInfo, SyncJob } from '$lib/types';

export const load: PageServerLoad = async ({ fetch }) => {
	const [connections, syncStatus] = await Promise.all([
		apiGet<{ connections: ConnectionInfo[] }>(fetch, '/api/connections'),
		apiGet<{ jobs: SyncJob[] }>(fetch, '/api/sync/status')
	]);
	return { connections: connections.connections, jobs: syncStatus.jobs };
};
