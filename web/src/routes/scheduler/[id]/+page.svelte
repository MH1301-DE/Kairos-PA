<script lang="ts">
	import JobEditor from '$lib/components/JobEditor.svelte';
	import type { ActionData, PageData } from './$types';

	let { data, form }: { data: PageData; form: ActionData } = $props();
</script>

<h1>{data.job.name} bearbeiten</h1>
{#if data.job.running}
	<p class="t-caption">Der Job läuft gerade; Änderungen gelten ab dem nächsten Lauf.</p>
{/if}
{#key data.job.id}
	<JobEditor
		actions={data.actions}
		defaultTimezone={data.defaultTimezone}
		job={data.job}
		errors={form?.errors ?? {}}
	/>
{/key}
