<!-- web/src/lib/components/StatusPill.svelte -->
<script lang="ts">
	import type { Snippet } from 'svelte';

	// neutral = open circle, attention = diamond, deviation = triangle; never color alone
	let {
		tone = 'neutral',
		children
	}: { tone?: 'neutral' | 'attention' | 'deviation'; children: Snippet } = $props();
</script>

<span class="status-pill {tone}" data-tone={tone}>{@render children()}</span>
