import { describe, it, expect } from 'vitest';
import { mergeTileAsOf } from '../../src/lib/dashboardTiles';

describe('mergeTileAsOf', () => {
	const serverTiles = [
		{ moduleId: 'hrv_baseline', result: null, error: null },
		{ moduleId: 'trimp', result: null, error: null }
	];

	it('defaults every tile to today when nothing was manually picked', () => {
		const tiles = mergeTileAsOf(serverTiles, new Map(), '2026-09-09');
		expect(tiles.map((t) => t.asOf)).toEqual(['2026-09-09', '2026-09-09']);
	});

	it('preserves a manually picked date instead of resetting it to today', () => {
		// this is the "Aktualisieren" regression: load() always re-fetches
		// data.tiles for today, so without manualAsOf a user-picked earlier
		// date silently snapped back to today on every refresh
		const manualAsOf = new Map([['hrv_baseline', '2026-09-08']]);
		const tiles = mergeTileAsOf(serverTiles, manualAsOf, '2026-09-09');
		expect(tiles.find((t) => t.moduleId === 'hrv_baseline')?.asOf).toBe('2026-09-08');
		expect(tiles.find((t) => t.moduleId === 'trimp')?.asOf).toBe('2026-09-09');
	});

	it('resets loading to false for every tile', () => {
		const tiles = mergeTileAsOf(serverTiles, new Map(), '2026-09-09');
		expect(tiles.every((t) => t.loading === false)).toBe(true);
	});
});
