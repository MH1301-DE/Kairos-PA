<!-- web/src/lib/components/ValueTile.svelte -->
<script lang="ts">
	import type { MetricResult } from '../types';
	import type { ModuleDef } from '../modules';
	import ConfidenceBadge from './ConfidenceBadge.svelte';
	import InfoTooltip from './InfoTooltip.svelte';

	let { result, module }: { result: MetricResult; module: ModuleDef } = $props();
</script>

<div class="tile value-tile">
	<div class="tile-header">
		<h3>{module.title}</h3>
		<InfoTooltip text={module.description} />
	</div>
	{#if result.confidence === 'insufficient_data' || result.value === null}
		<p class="empty">Nicht genug Daten</p>
	{:else if module.fields}
		{@const dict = result.value as Record<string, number>}
		<dl>
			{#each module.fields as field (field.key)}
				<dt>{field.label}</dt>
				<dd class="figure">
					{(dict[field.key] ?? 0).toFixed(2)} <span class="unit">{field.unit ?? ''}</span>
				</dd>
			{/each}
		</dl>
		{#if module.trendKey}
			{@const delta = dict[module.trendKey] ?? 0}
			<p class="trend figure">{delta < 0 ? '↓' : delta > 0 ? '↑' : '→'} {delta.toFixed(1)} bpm</p>
		{/if}
	{:else}
		<p class="scalar figure">
			{(result.value as number).toFixed(1)} <span class="unit">{result.unit}</span>
		</p>
	{/if}
	<ConfidenceBadge confidence={result.confidence} />
</div>

<style>
	dl {
		margin: 0;
		display: flex;
		flex-direction: column;
		gap: var(--space-1);
	}
	dt {
		font-size: var(--text-xs);
		color: var(--color-text-muted);
	}
	dd {
		margin: 0 0 var(--space-2);
		font-size: var(--text-xl);
		color: var(--color-text);
	}
	.scalar {
		font-size: var(--text-3xl);
		color: var(--color-text);
		line-height: 1;
	}
	.unit {
		font-family: var(--font-body);
		font-size: var(--text-sm);
		color: var(--color-text-muted);
	}
	.trend {
		font-size: var(--text-sm);
		color: var(--color-text-muted);
	}
</style>
