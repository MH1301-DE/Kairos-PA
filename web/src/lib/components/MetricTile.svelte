<!-- web/src/lib/components/MetricTile.svelte -->
<script lang="ts">
	import type { MetricResult } from '../types';
	import type { ModuleDef } from '../modules';
	import ValueTile from './ValueTile.svelte';
	import BarTile from './BarTile.svelte';
	import GaugeTile from './GaugeTile.svelte';

	let { result, module }: { result: MetricResult; module: ModuleDef } = $props();
</script>

{#if module.form === 'value'}
	<ValueTile {result} {module} />
{:else if module.form === 'bar'}
	<BarTile {result} {module} />
{:else if module.form === 'gauge'}
	<GaugeTile {result} {module} />
{/if}
