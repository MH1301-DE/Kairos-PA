import type { MetricResult } from './types';

export interface TileState {
	moduleId: string;
	result: MetricResult | null;
	error: string | null;
	asOf: string;
	loading: boolean;
}

interface ServerTile {
	moduleId: string;
	result: MetricResult | null;
	error: string | null;
}

// load() (server, +page.server.ts) always fetches every tile for "today" --
// merges that fresh snapshot with any date a user picked via a tile's "Stand"
// picker, so "Aktualisieren" (which re-runs load()) doesn't silently reset a
// deliberately-picked earlier date back to today.
export function mergeTileAsOf(
	serverTiles: ServerTile[],
	manualAsOf: Map<string, string>,
	today: string
): TileState[] {
	return serverTiles.map((t) => ({
		...t,
		asOf: manualAsOf.get(t.moduleId) ?? today,
		loading: false
	}));
}
