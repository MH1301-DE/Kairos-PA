<script lang="ts">
	import JobEditor from '$lib/components/JobEditor.svelte';
	import { TEMPLATES } from '$lib/scheduler';
	import type { ActionData, PageData } from './$types';

	let { data, form }: { data: PageData; form: ActionData } = $props();
	const template = $derived(data.template !== null ? (TEMPLATES[data.template] ?? null) : null);
</script>

<h1>Neuer Job</h1>
<JobEditor
	actions={data.actions}
	defaultTimezone={data.defaultTimezone}
	{template}
	errors={form?.errors ?? {}}
/>
