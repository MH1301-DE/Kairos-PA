<!-- web/src/lib/components/RangeBar.svelte -->
<script lang="ts">
	// "Lage-Leiste": today's value against the personal normal band (80 % of the last 60 days)
	let {
		min,
		max,
		bandLow,
		bandHigh,
		value,
		unit = '',
		bandDays = null,
		bandDaysNeeded = 14
	}: {
		min: number;
		max: number;
		bandLow: number | null;
		bandHigh: number | null;
		value: number | null;
		unit?: string;
		bandDays?: number | null;
		bandDaysNeeded?: number;
	} = $props();

	const pct = (v: number) => Math.min(100, Math.max(0, ((v - min) / (max - min)) * 100));

	let bandReady = $derived(
		bandLow !== null &&
			bandHigh !== null &&
			max > min &&
			(bandDays === null || bandDays >= bandDaysNeeded)
	);
	let fmt = (v: number) => v.toLocaleString('de-DE', { maximumFractionDigits: 1 });
</script>

<div class="range-bar">
	<div
		class="track"
		role="img"
		aria-label={value === null
			? 'kein Wert'
			: bandReady
				? `${fmt(value)} ${unit}, Normalbereich ${fmt(bandLow!)}–${fmt(bandHigh!)}`
				: `${fmt(value)} ${unit}`}
	>
		{#if bandReady}
			<div
				class="band"
				style:left="{pct(bandLow!)}%"
				style:width="{pct(bandHigh!) - pct(bandLow!)}%"
			></div>
		{/if}
		{#if value !== null && max > min}
			<div class="mark" style:left="{pct(value)}%"></div>
		{/if}
	</div>
	<div class="scale">
		<span>{fmt(min)}</span>
		{#if bandReady}
			<span class="normal">dein Normalbereich {fmt(bandLow!)}–{fmt(bandHigh!)}</span>
		{:else}
			<span class="normal">Band entsteht · {bandDays ?? 0} von {bandDaysNeeded} Tagen</span>
		{/if}
		<span>{fmt(max)}</span>
	</div>
</div>

<style>
	.range-bar {
		display: flex;
		flex-direction: column;
		gap: var(--space-2);
	}
	.track {
		position: relative;
		height: 6px;
		border-radius: 3px;
		background: var(--data-track);
	}
	.band {
		position: absolute;
		top: 0;
		bottom: 0;
		border-radius: 3px;
		background: var(--data-band);
	}
	.mark {
		position: absolute;
		top: -5px;
		width: 2px;
		height: 16px;
		margin-left: -1px;
		border-radius: 1px;
		background: var(--text);
	}
	.scale {
		display: flex;
		justify-content: space-between;
		font: var(--type-caption);
		color: var(--text-faint);
	}
	.normal {
		color: var(--text-secondary);
	}
</style>
