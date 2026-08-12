<!-- web/src/routes/onboarding/+page.svelte -->
<script lang="ts">
	import { enhance } from '$app/forms';
	import { resolve } from '$app/paths';
	import type { ActionData } from './$types';

	let { form }: { form: ActionData } = $props();
</script>

<h1>Garmin-Verbindung einrichten</h1>
<p class="lede">
	Verbinde dein Garmin-Konto, damit Kairos deine Trainings- und Erholungsdaten lesen kann.
</p>

{#if form?.success}
	<div class="tile success-panel">
		<p class="status-success">Verbunden mit {form.email}.</p>
		<a href={resolve('/sync')} class="btn btn-primary">Zum Sync-Status</a>
	</div>
{:else}
	<form method="POST" use:enhance class="tile">
		<label class="field">
			E-Mail
			<input type="email" name="email" value={form?.email ?? ''} required />
		</label>
		<label class="field">
			Passwort
			<!-- never pre-filled: the server does not echo the password back -->
			<input type="password" name="password" required />
		</label>
		{#if form?.mfaRequired}
			<label class="field">
				MFA-Code (aus E-Mail/App)
				<!-- svelte-ignore a11y_autofocus -->
				<input type="text" name="mfa_token" required autofocus />
			</label>
		{/if}
		{#if form?.error}
			<p class="status-error">{form.error}</p>
		{/if}
		<button type="submit" class="btn btn-primary">Verbinden</button>
	</form>
{/if}

<style>
	.lede {
		color: var(--color-text-muted);
		max-width: 32rem;
	}
	form,
	.success-panel {
		display: flex;
		flex-direction: column;
		gap: var(--space-4);
		max-width: 24rem;
	}
	.success-panel .btn {
		align-self: flex-start;
	}
</style>
