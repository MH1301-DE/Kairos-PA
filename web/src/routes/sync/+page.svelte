<!-- web/src/routes/sync/+page.svelte -->
<script lang="ts">
	import { resolve } from '$app/paths';
	import type { PageData } from './$types';

	let { data }: { data: PageData } = $props();
	let garminConnection = $derived(data.connections.find((c) => c.connector === 'garmin'));
</script>

<h1>Sync-Status</h1>

{#if !garminConnection}
	<div class="tile">
		<p>Keine Garmin-Verbindung.</p>
		<a href={resolve('/onboarding')} class="btn btn-primary">Jetzt einrichten</a>
	</div>
{:else}
	<p class="connection-line">
		Garmin: <span class="figure">{garminConnection.status}</span>
		({garminConnection.external_account})
	</p>

	<div class="tile">
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
	</div>
{/if}

<style>
	.connection-line {
		color: var(--color-text-muted);
	}
</style>
