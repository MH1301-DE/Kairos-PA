<!-- web/src/lib/components/FreshnessIndicator.svelte -->
<script lang="ts">
	import { resolve } from '$app/paths';
	import type { Freshness } from '../design/freshness';

	// the calm case is almost invisible; every state links to the sync page
	let { value }: { value: Freshness } = $props();
</script>

{#if value.state === 'abgelaufen'}
	<span class="freshness abgelaufen" data-state={value.state}>
		<span class="mark" aria-hidden="true"></span>
		<a href={resolve('/sync')} class="label">{value.label}</a>
		<a href={resolve('/onboarding')} class="relogin">Neu anmelden</a>
	</span>
{:else}
	<a href={resolve('/sync')} class="freshness {value.state}" data-state={value.state}>
		<span class="mark" aria-hidden="true"></span>
		<span class="label">{value.label}</span>
	</a>
{/if}

<style>
	.freshness {
		display: inline-flex;
		align-items: center;
		gap: var(--space-2);
		font: var(--type-caption);
		color: var(--text-faint);
		border-radius: var(--radius-pill);
		white-space: nowrap;
	}
	.freshness:hover {
		color: var(--text-secondary);
	}
	.mark {
		flex: none;
		width: 6px;
		height: 6px;
		border-radius: 50%;
		background: var(--data-band);
	}

	.laeuft {
		color: var(--text-secondary);
	}
	.laeuft .mark {
		width: 10px;
		height: 10px;
		background: none;
		border: 1.5px solid var(--data-band);
		border-top-color: var(--text-secondary);
		animation: spin 0.9s linear infinite;
	}

	.veraltet {
		color: var(--status-attention-text);
		background: var(--status-attention-bg);
		padding: 7px 14px;
	}
	.veraltet:hover {
		color: var(--status-attention-text);
	}
	.veraltet .mark {
		width: 7px;
		height: 7px;
		border-radius: 0;
		background: var(--status-attention-mark);
		transform: rotate(45deg);
	}

	.abgelaufen {
		color: var(--text);
		background: var(--status-deviation-bg);
		padding: 5px 5px 5px 14px;
		gap: 10px;
	}
	.abgelaufen .label {
		color: var(--text);
	}
	.abgelaufen .mark {
		width: 0;
		height: 0;
		border-radius: 0;
		background: none;
		border-left: 4.5px solid transparent;
		border-right: 4.5px solid transparent;
		border-bottom: 8px solid var(--status-deviation-mark);
	}
	.relogin {
		background: var(--accent);
		color: var(--accent-ink);
		font-weight: 500;
		padding: 4px 12px;
		border-radius: var(--radius-pill);
	}
	.relogin:hover {
		background: var(--accent-hover);
		color: var(--accent-ink);
	}

	@keyframes spin {
		to {
			transform: rotate(360deg);
		}
	}
</style>
