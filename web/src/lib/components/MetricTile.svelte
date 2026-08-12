<!-- web/src/lib/components/MetricTile.svelte -->
<script lang="ts">
	import type { MetricResult } from '../types';
	import type { ModuleDef } from '../modules';
	import ValueTile from './ValueTile.svelte';

	let { result, module }: { result: MetricResult; module: ModuleDef } = $props();
</script>

{#if module.form === 'value'}
	<ValueTile {result} {module} />
{:else if module.form === 'bar'}
	<div class="pending-form">{module.title} (Balkendiagramm folgt in Task 7)</div>
{:else if module.form === 'gauge'}
	<div class="pending-form">{module.title} (Gauge folgt in Task 8)</div>
{/if}
