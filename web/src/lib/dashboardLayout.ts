import type { DashboardTileLayout } from './types';
import type { ModuleDef } from './modules';

export interface OrderedTile {
	module: ModuleDef;
	visible: boolean;
}

// Orders every module by its layout position -- hidden modules stay in the
// result (visible: false) so an edit UI can still offer to re-enable them.
// A module with no matching layout row (e.g. one added after the user's
// last save) is appended at the end, visible -- a stale layout must never
// silently hide a real module.
export function orderModules(modules: ModuleDef[], layout: DashboardTileLayout[]): OrderedTile[] {
	const byId = new Map(layout.map((entry) => [entry.module_id, entry]));
	const known: { tile: OrderedTile; position: number }[] = [];
	const unknown: OrderedTile[] = [];

	for (const module of modules) {
		const entry = byId.get(module.moduleId);
		if (!entry) {
			unknown.push({ module, visible: true });
			continue;
		}
		known.push({ tile: { module, visible: entry.visible }, position: entry.position });
	}

	known.sort((a, b) => a.position - b.position);
	return [...known.map((k) => k.tile), ...unknown];
}

// Same ordering, but filtered down to what should actually render on the
// (non-edit-mode) dashboard.
export function applyLayout(modules: ModuleDef[], layout: DashboardTileLayout[]): ModuleDef[] {
	return orderModules(modules, layout)
		.filter((t) => t.visible)
		.map((t) => t.module);
}
