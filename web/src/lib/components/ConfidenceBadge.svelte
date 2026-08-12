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
	<span
		data-testid="confidence-badge"
		class="badge confidence-badge confidence-{confidence}"
		class:badge-warning={confidence === 'medium'}
		class:badge-danger={confidence === 'low'}
	>
		Konfidenz: {label}
	</span>
{/if}
