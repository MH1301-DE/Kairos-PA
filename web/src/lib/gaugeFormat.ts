// Picks how many decimal places a gauge's axis-tick labels need so
// consecutive ticks stay distinguishable, without showing more precision
// than the tick spacing warrants. See GaugeTile.svelte for why this exists:
// ECharts' default axis-label formatting only looks right for a "nice" fixed
// range like ACWR's 0-2 -- hrv_baseline's min/max are derived per-user from a
// real baseline +/- stddev (e.g. 62.56-124.54), which produced a dozen
// overlapping multi-decimal labels crammed onto a small gauge, unreadable.
export function gaugeAxisDecimals(min: number, max: number, splitNumber: number): number {
	const step = (max - min) / splitNumber;
	if (step >= 1) return 0;
	if (step >= 0.1) return 1;
	return 2;
}
