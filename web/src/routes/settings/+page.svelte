<!-- web/src/routes/settings/+page.svelte -->
<script lang="ts">
	import { enhance } from '$app/forms';
	import type { PageData, ActionData } from './$types';

	let { data, form }: { data: PageData; form: ActionData } = $props();

	let profile = $derived(data.profile);
</script>

<h1>Einstellungen</h1>
<p class="lede">
	Diese Angaben bestimmen deine HF-Zonen und die Trainingslast (TRIMP).
</p>

<div class="tile">
	<h2>Verwendete HFmax</h2>
	{#if profile.hr_max_used !== null}
		<p class="hr-used">
			<strong>{profile.hr_max_used} bpm</strong>
			<span class="source">({profile.hr_max_source})</span>
		</p>
	{:else}
		<p>HFmax fehlt – bitte unten eintragen.</p>
	{/if}
	{#if profile.hr_max_warning}
		<p class="badge badge-warning">{profile.hr_max_warning}</p>
	{/if}
</div>

<div class="tile">
	<form method="POST" action="?/save" use:enhance class="profile-form">
		<label class="field">
			Gemessene HFmax (bpm)
			<input
				type="number"
				name="hr_max_override"
				min="120"
				max="230"
				step="1"
				value={profile.hr_max_override ?? ''}
			/>
		</label>
		<p class="hint">
			Trag hier deinen höchsten selbst gemessenen Puls ein, z. B. aus einem Maximaltest oder
			einem harten Wettkampf. Die Faustformel 220 − Alter streut individuell stark (oft um
			± 10 bpm und mehr) und wird nur genutzt, wenn hier nichts steht.
		</p>
		<label class="field">
			Geburtsdatum
			<input type="date" name="birth_date" min="1900-01-01" value={profile.birth_date ?? ''} />
		</label>
		<label class="field">
			Ruhepuls (bpm)
			<input
				type="number"
				name="resting_hr_override"
				min="30"
				max="100"
				step="1"
				value={profile.resting_hr_override ?? ''}
			/>
		</label>
		<p class="hint">Leer lassen, um einen Wert zu löschen.</p>
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
		max-width: 32rem;
	}
	.hr-used {
		display: flex;
		align-items: baseline;
		gap: var(--space-2);
	}
	.source,
	.hint {
		color: var(--text-muted);
		font: var(--type-caption);
	}
	.profile-form {
		display: flex;
		flex-direction: column;
		gap: var(--space-3);
		max-width: 32rem;
	}
</style>
