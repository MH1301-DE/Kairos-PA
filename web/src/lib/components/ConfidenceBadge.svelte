<!-- web/src/lib/components/ConfidenceBadge.svelte -->
<script lang="ts">
	import type { Confidence } from '../types';

	let { confidence }: { confidence: Confidence } = $props();

	const LABELS: Record<Confidence, string | null> = {
		high: null,
		medium: 'mittel',
		low: 'niedrig',
		insufficient_data: null
	};

	let label = $derived(LABELS[confidence]);
</script>

{#if label}
	<span data-testid="confidence-badge" class="confidence-badge confidence-{confidence}">
		Konfidenz: {label}
	</span>
{/if}

<style>
	.confidence-badge {
		font-size: 0.75rem;
		padding: 0.1rem 0.4rem;
		border-radius: 0.25rem;
		background: #fef3c7;
		color: #92400e;
	}
</style>
