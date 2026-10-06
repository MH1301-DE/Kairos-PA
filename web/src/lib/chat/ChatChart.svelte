<script lang="ts">
	import EChartsBase from '$lib/components/EChartsBase.svelte';
	import { chartOption } from './chartOption';

	let { component, config }: { component: string; config: Record<string, unknown> } = $props();

	const option = $derived(chartOption(component, config));
	const title = $derived(String(config.title ?? ''));
	const items = $derived(
		(config.items ?? []) as { label: string; value: string | number; unit?: string | null }[]
	);
	const columns = $derived((config.columns ?? []) as string[]);
	const rows = $derived((config.rows ?? []) as (string | number)[][]);
</script>

<figure class="chat-chart">
	{#if option}
		<EChartsBase {option} renderer="svg" />
	{:else if component === 'StatCard'}
		<figcaption>{title}</figcaption>
		<dl class="stat-grid">
			{#each items as item, i (i)}
				<div class="stat">
					<dt>{item.label}</dt>
					<dd>{item.value}{item.unit ? ' ' + item.unit : ''}</dd>
				</div>
			{/each}
		</dl>
	{:else if component === 'Table'}
		<figcaption>{title}</figcaption>
		<div class="table-wrap">
			<table>
				<thead>
					<tr>
						{#each columns as col, i (i)}<th>{col}</th>{/each}
					</tr>
				</thead>
				<tbody>
					{#each rows as row, r (r)}
						<tr>
							{#each row as cell, c (c)}<td>{cell}</td>{/each}
						</tr>
					{/each}
				</tbody>
			</table>
		</div>
	{/if}
</figure>

<style>
	.chat-chart {
		margin: var(--space-2) 0 0;
		width: min(32rem, 100%);
	}
	figcaption {
		font-size: var(--text-sm);
		font-weight: 500;
		margin-bottom: var(--space-2);
	}
	.stat-grid {
		display: grid;
		grid-template-columns: repeat(auto-fill, minmax(7rem, 1fr));
		gap: var(--space-2);
		margin: 0;
	}
	.stat {
		background: var(--color-surface);
		border-radius: var(--radius-sm);
		padding: var(--space-2);
	}
	dt {
		font-size: var(--text-xs);
		color: var(--color-text-muted);
	}
	dd {
		margin: 0;
		font-size: 1.125rem;
		font-variant-numeric: tabular-nums;
	}
	.table-wrap {
		overflow-x: auto;
	}
	table {
		border-collapse: collapse;
		font-size: var(--text-sm);
		width: 100%;
	}
	th,
	td {
		border-bottom: 1px solid var(--color-border);
		padding: var(--space-1) var(--space-2);
		text-align: left;
	}
	th {
		color: var(--color-text-muted);
		font-weight: 500;
	}
</style>
