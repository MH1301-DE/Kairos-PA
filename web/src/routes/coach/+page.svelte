<!-- web/src/routes/coach/+page.svelte -->
<script lang="ts">
	import { enhance } from '$app/forms';
	import { resolve } from '$app/paths';
	import type { PageData, ActionData } from './$types';

	let { data, form }: { data: PageData; form: ActionData } = $props();

	const DAYS: [string, string][] = [
		['mo', 'Montag'],
		['di', 'Dienstag'],
		['mi', 'Mittwoch'],
		['do', 'Donnerstag'],
		['fr', 'Freitag'],
		['sa', 'Samstag'],
		['so', 'Sonntag']
	];

	let profile = $derived(data.coach.profile);
	let availability = $derived(profile?.availability ?? {});
</script>

<h1>Coach-Profil</h1>
<p class="lede">
	Plantyp und Trainingszeiten für den Coach. Das Ziel legst du unter
	<a href={resolve('/goals')}>Ziele</a> an (mit Datum, z. B. „Halbmarathon“). Danach im Chat: „Schlag
	mir einen Trainingsplan vor.“
</p>

<div class="tile">
	<form method="POST" action="?/save" use:enhance class="coach-form">
		<label class="field">
			Plantyp
			<select name="plan_type">
				{#each data.coach.plan_types as pt (pt.id)}
					<option value={pt.id} selected={profile?.plan_type === pt.id}>{pt.titel}</option>
				{/each}
			</select>
		</label>

		<table>
			<thead>
				<tr><th>Tag</th><th>Max. Minuten</th><th>Qualität</th><th>Uhrzeit</th></tr>
			</thead>
			<tbody>
				{#each DAYS as [key, label] (key)}
					<tr>
						<td>{label}</td>
						<td>
							<input
								type="number"
								name="{key}_max_min"
								min="0"
								max="600"
								step="5"
								value={availability[key]?.max_min ?? 0}
							/>
						</td>
						<td>
							<input
								type="checkbox"
								name="{key}_quality"
								checked={availability[key]?.quality ?? false}
							/>
						</td>
						<td><input type="time" name="{key}_time" value={availability[key]?.time ?? ''} /></td>
					</tr>
				{/each}
			</tbody>
		</table>
		<p class="hint">
			0 Minuten = kein Training. „Qualität“ markiert Tage, an denen harte Einheiten möglich sind.
			Ohne Uhrzeit startet die Einheit um 07:00.
		</p>
		{#if form?.saveError}
			<p class="status-error">{form.saveError}</p>
		{/if}
		{#if form?.saved}
			<p>Gespeichert.</p>
		{/if}
		<button type="submit" class="btn btn-primary">Speichern</button>
	</form>
</div>

<style>
	.lede {
		color: var(--color-text-muted);
		max-width: 36rem;
	}
	.hint {
		color: var(--text-muted);
		font: var(--type-caption);
	}
	.coach-form {
		display: flex;
		flex-direction: column;
		gap: var(--space-3);
		max-width: 36rem;
	}
	table {
		border-collapse: collapse;
	}
	th,
	td {
		padding: var(--space-1) var(--space-2);
		text-align: left;
	}
	input[type='number'] {
		width: 5rem;
	}
</style>
