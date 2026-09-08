import type { LayoutServerLoad } from './$types';
import { apiGet } from '$lib/api';
import type { ConnectionInfo, SyncJob } from '$lib/types';

export const load: LayoutServerLoad = async ({ cookies, fetch, depends }) => {
	depends('layout:connections');
	// hooks.server.ts already guarantees a session cookie exists on every
	// non-public route reachable here; we don't decode it (opaque to the
	// frontend, backend owns session state) — just confirm presence for the nav.
	const authenticated = cookies.get('session_id') !== undefined;
	if (!authenticated) {
		return { authenticated, connections: [] as ConnectionInfo[], jobs: [] as SyncJob[] };
	}
	try {
		const [connections, syncStatus] = await Promise.all([
			apiGet<{ connections: ConnectionInfo[] }>(fetch, '/api/connections'),
			apiGet<{ jobs: SyncJob[] }>(fetch, '/api/sync/status')
		]);
		return { authenticated, connections: connections.connections, jobs: syncStatus.jobs };
	} catch {
		// menu degrades gracefully -- the page-level loads already handle 401s
		return { authenticated, connections: [] as ConnectionInfo[], jobs: [] as SyncJob[] };
	}
};
