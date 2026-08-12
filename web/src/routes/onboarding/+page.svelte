<!-- web/src/routes/onboarding/+page.svelte -->
<script lang="ts">
	import { enhance } from '$app/forms';
	import { resolve } from '$app/paths';
	import type { ActionData } from './$types';

	let { form }: { form: ActionData } = $props();
</script>

<h1>Garmin-Verbindung einrichten</h1>

{#if form?.success}
	<p class="success">
		Verbunden mit {form.email}.
		<a href={resolve('/sync')}>Zum Sync-Status</a>
	</p>
{:else}
	<form method="POST" use:enhance>
		<label>
			E-Mail
			<input type="email" name="email" value={form?.email ?? ''} required />
		</label>
		<label>
			Passwort
			<!-- never pre-filled: the server does not echo the password back -->
			<input type="password" name="password" required />
		</label>
		{#if form?.mfaRequired}
			<label>
				MFA-Code (aus E-Mail/App)
				<!-- svelte-ignore a11y_autofocus -->
				<input type="text" name="mfa_token" required autofocus />
			</label>
		{/if}
		{#if form?.error}
			<p class="error">{form.error}</p>
		{/if}
		<button type="submit">Verbinden</button>
	</form>
{/if}

<style>
	form {
		display: flex;
		flex-direction: column;
		gap: 0.75rem;
		max-width: 320px;
	}
	.error {
		color: #b91c1c;
	}
	.success {
		color: #15803d;
	}
</style>
