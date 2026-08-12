<!-- web/src/routes/sync/+page.svelte -->
<script lang="ts">
	import { resolve } from '$app/paths';
	import type { PageData } from './$types';

	let { data }: { data: PageData } = $props();
	let garminConnection = $derived(data.connections.find((c) => c.connector === 'garmin'));
</script>

<h1>Sync-Status</h1>

{#if !garminConnection}
	<p>Keine Garmin-Verbindung. <a href={resolve('/onboarding')}>Jetzt einrichten</a></p>
{:else}
	<p>Garmin: {garminConnection.status} ({garminConnection.external_account})</p>

	<table>
		<thead>
			<tr>
				<th>Kind</th>
				<th>Status</th>
				<th>Verarbeitete Fenster</th>
				<th>Fehler</th>
			</tr>
		</thead>
		<tbody>
			{#each data.jobs as job (job.job_id)}
				<tr>
					<td>{job.kind}</td>
					<td>{job.status}</td>
					<td>{job.windows_processed}</td>
					<td>{job.error ?? '–'}</td>
				</tr>
			{/each}
		</tbody>
	</table>
{/if}
