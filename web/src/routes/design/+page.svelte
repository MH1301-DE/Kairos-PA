<!-- living reference for the "Ruhe" design system (claude.ai/design: Kairos Designsystem) -->
<script lang="ts">
	import StatusPill from '$lib/components/StatusPill.svelte';
	import RangeBar from '$lib/components/RangeBar.svelte';
	import FreshnessIndicator from '$lib/components/FreshnessIndicator.svelte';
	import ContextChip from '$lib/components/ContextChip.svelte';
	import { colors, hrZoneColors, sleepStageColors, heatColors } from '$lib/design/palette';
	import MetricTile from '$lib/components/MetricTile.svelte';
	import { moduleById } from '$lib/modules';
	import type { MetricResult } from '$lib/types';

	const TODAY = new Date().toISOString().slice(0, 10);
	const res = (
		metric_id: string,
		value: MetricResult['value'],
		have = 7,
		need = 7
	): MetricResult => ({
		metric_id,
		variant: 'default',
		value,
		unit: '',
		confidence: 'high',
		coverage_days: have,
		coverage_required_days: need,
		as_of: TODAY
	});
	const SAMPLES = [
		{
			id: 'hrv_baseline',
			label: 'Rundanzeige · vollständig',
			r: res('hrv_baseline', { today: 62, baseline_low: 55, baseline_high: 68 }, 60, 14)
		},
		{ id: 'acwr', label: 'Rundanzeige · teilweise', r: res('acwr', { ratio: 1.42 }, 5, 7) },
		{ id: 'sleep_debt', label: 'Kennzahl', r: res('sleep_debt', 3.2) },
		{
			id: 'resting_hr_trend',
			label: 'Kennzahl · mehrere Werte',
			r: res('resting_hr_trend', { recent_avg: 52, prior_avg: 55, delta_bpm: -3 }, 37, 37)
		},
		{
			id: 'training_load',
			label: 'Belastung',
			r: res('training_load', { ctl: 48, atl: 55, tsb: -7 }, 42, 42)
		},
		{
			id: 'hr_zone_distribution',
			label: 'Verteilung',
			r: res(
				'hr_zone_distribution',
				{ zone_1: 8520, zone_2: 5760, zone_3: 3240, zone_4: 1320, zone_5: 480 },
				1,
				1
			)
		},
		{
			id: 'monotony_strain',
			label: 'Leer',
			r: { ...res('monotony_strain', null, 3, 7), confidence: 'insufficient_data' as const }
		},
		{ id: 'trimp', label: 'Fehler', r: null },
		{ id: 'trimp', label: 'Laden', r: res('trimp', 42), loading: true }
	];

	const SWATCHES = [
		'bg',
		'surface',
		'surface-raised',
		'surface-hover',
		'text',
		'text-secondary',
		'text-muted',
		'text-faint',
		'accent',
		'accent-hover',
		'accent-subtle',
		'data-band',
		'status-neutral-mark',
		'status-attention-mark',
		'status-deviation-mark',
		'data-primary'
	] as const;

	const TYPE = [
		['t-metric-xl', '72', '72 / 300'],
		['t-metric-lg', '5:22 h', '44 / 300'],
		['t-headline', 'Du bist erholt in die Woche gestartet.', '34 / 300'],
		['t-metric-md', '18,2 km', '28 / 400'],
		['t-title', 'Profil & Verbindungen', '22 / 400'],
		['t-subtitle', 'Garmin braucht eine neue Anmeldung', '17 / 500'],
		['', 'Seit dem 14. September liegt deine HRV höher.', '15 / 400'],
		['t-body-sm', 'dein Normalbereich 55–68', '14 / 400'],
		['t-caption', 'Ø aus 4 von 7 Nächten', '13 / 400'],
		['t-micro', '24. Aug   7. Sep   21. Sep', '12 / 400']
	] as const;

	const sleep = sleepStageColors();
	const SLEEP = [
		['Tief', sleep.deep],
		['REM', sleep.rem],
		['Leicht', sleep.light],
		['Wach', sleep.awake]
	] as const;

	let chips = $state(['HRV · letzte 30 Tage', 'Schlaf · diese Woche']);
</script>

<svelte:head><title>Designsystem · Kairos</title></svelte:head>

<div class="ds">
	<header>
		<p class="t-caption">Kairos · Designsystem · Richtung „Ruhe“</p>
		<h1 class="t-metric-lg">Ruhig, nachvollziehbar, persönlich.</h1>
		<p class="lead">
			Grün gehört der Interaktion. Status hat eine eigene, gedämpfte Skala und nie nur Farbe. Jeder
			Wert steht neben dem persönlichen Normalbereich. Lücken werden gezeigt, nicht geglättet.
			Trennung über Helligkeit und Abstand, nicht über Linien.
		</p>
	</header>

	<section>
		<h2>Farbe</h2>
		<div class="swatches">
			{#each SWATCHES as name (name)}
				<div class="swatch">
					<div class="chip" style:background={colors.dark[name]}></div>
					<span class="t-caption">{name}</span>
					<code>{colors.dark[name]}</code>
				</div>
			{/each}
		</div>
		<div class="grid3">
			<div class="tile small">
				<h3>Herzfrequenzzonen</h3>
				<div class="ramp">
					{#each hrZoneColors() as c, i (c)}
						<div style:background={c}>Z{i + 1}</div>
					{/each}
				</div>
			</div>
			<div class="tile small">
				<h3>Schlafphasen</h3>
				<div class="ramp">
					{#each SLEEP as [n, c] (n)}
						<div style:background={c}>{n}</div>
					{/each}
				</div>
			</div>
			<div class="tile small">
				<h3>Heatmap</h3>
				<div class="heat">
					{#each heatColors() as c (c)}
						<span style:background={c}></span>
					{/each}
					<span class="none"></span>
				</div>
			</div>
		</div>
	</section>

	<section>
		<h2>Typografie</h2>
		<div class="tile type">
			{#each TYPE as [cls, sample, spec] (spec)}
				<div class="type-row">
					<code>{cls || 'body'}</code>
					<span class={cls}>{sample}</span>
					<code>{spec}</code>
				</div>
			{/each}
		</div>
	</section>

	<section>
		<h2>Grundelemente</h2>
		<div class="grid3">
			<div class="tile small">
				<h3>Schaltflächen</h3>
				<div class="row">
					<button class="btn btn-primary">Bestätigen</button>
					<button class="btn btn-secondary">Anpassen</button>
					<button class="btn btn-ghost">Verwerfen</button>
					<button class="btn btn-primary" disabled>Bestätigen</button>
				</div>
			</div>
			<div class="tile small">
				<h3>Eingabefelder</h3>
				<label class="field">Name <input value="Jonas Weber" /></label>
				<label class="field">
					Ruhepuls <input value="300" aria-invalid="true" />
					<span class="field-error">Bitte einen Wert zwischen 30 und 120 eingeben.</span>
				</label>
			</div>
			<div class="tile small">
				<h3>Status &amp; Chips</h3>
				<div class="col">
					<StatusPill>im Normalbereich</StatusPill>
					<StatusPill tone="attention">leicht ermüdet</StatusPill>
					<StatusPill tone="deviation">unter dem Band</StatusPill>
				</div>
				<p>
					Deine HRV liegt bei <span class="chip-evidence">61 ms</span>, davor bei
					<span class="chip-evidence" aria-current="true">56 ms</span>.
				</p>
				<div class="row">
					{#each chips as c (c)}
						<ContextChip label={c} onremove={() => (chips = chips.filter((x) => x !== c))} />
					{/each}
				</div>
			</div>
		</div>
		<div class="grid2">
			<div class="tile small">
				<h3>Aktualitätsindikator</h3>
				<div class="col">
					<FreshnessIndicator value={{ state: 'aktuell', label: 'aktuell · 06:42' }} />
					<FreshnessIndicator value={{ state: 'laeuft', label: 'Abgleich läuft · 2 von 4' }} />
					<FreshnessIndicator
						value={{ state: 'veraltet', label: 'Garmin-Stand von gestern, 22:10' }}
					/>
					<FreshnessIndicator
						value={{ state: 'abgelaufen', label: 'Garmin-Anmeldung abgelaufen' }}
					/>
				</div>
			</div>
			<div class="tile small">
				<h3>Lage-Leiste</h3>
				<div class="metric">
					<span class="t-metric-xl">62</span><span class="t-unit">ms</span>
				</div>
				<RangeBar min={40} max={80} bandLow={55} bandHigh={68} value={62} unit="ms" />
				<RangeBar min={40} max={80} bandLow={55} bandHigh={68} value={62} unit="ms" bandDays={9} />
			</div>
		</div>
	</section>

	<section>
		<h2>Kacheln · Zustände</h2>
		<div class="tiles">
			{#each SAMPLES as sample (sample.label)}
				<div class="col">
					<span class="t-caption">{sample.label}</span>
					<div class="tile-wrap">
						<MetricTile
							tile={{
								loading: sample.loading ?? false,
								result: sample.r,
								error: sample.r ? null : 'x'
							}}
							module={moduleById(sample.id)!}
							asOf={TODAY}
							today={TODAY}
							onretry={() => {}}
						/>
					</div>
				</div>
			{/each}
			<div class="col">
				<span class="t-caption">Bearbeiten</span>
				<div class="tile-wrap">
					<MetricTile
						tile={{ loading: false, result: res('sleep_debt', 1.4), error: null }}
						module={moduleById('sleep_debt')!}
						asOf={TODAY}
						today={TODAY}
						editing
						onremove={() => {}}
					/>
				</div>
			</div>
		</div>
	</section>
</div>

<style>
	.tiles {
		display: grid;
		gap: var(--space-5);
		grid-template-columns: repeat(auto-fill, minmax(min(100%, 340px), 1fr));
	}
	.tiles .col {
		align-items: stretch;
		gap: var(--space-2);
	}
	.tile-wrap {
		display: flex;
		flex-direction: column;
	}
	.ds {
		display: flex;
		flex-direction: column;
		gap: var(--space-16);
	}
	header {
		display: flex;
		flex-direction: column;
		gap: var(--space-4);
		max-width: 54rem;
	}
	header h1 {
		margin: 0;
	}
	.lead {
		font-size: 17px;
		line-height: 1.6;
		color: var(--text-secondary);
	}
	section {
		display: flex;
		flex-direction: column;
		gap: var(--space-6);
	}
	h2 {
		font: var(--type-title);
		margin: 0;
	}
	.swatches {
		display: grid;
		grid-template-columns: repeat(auto-fill, minmax(8rem, 1fr));
		gap: var(--space-3);
	}
	.swatch {
		display: flex;
		flex-direction: column;
		gap: var(--space-1);
	}
	.swatch .chip {
		height: 56px;
		border-radius: var(--radius-md);
		box-shadow: inset 0 0 0 1px var(--line-subtle);
	}
	code {
		font: 400 11px / 1.3 var(--font-mono);
		color: var(--text-faint);
	}
	.grid3,
	.grid2 {
		display: grid;
		gap: var(--space-6);
		grid-template-columns: repeat(auto-fit, minmax(18rem, 1fr));
	}
	.tile.small {
		min-height: 0;
		gap: var(--space-4);
	}
	.ramp {
		display: flex;
		gap: 4px;
		height: 44px;
	}
	.ramp div {
		flex: 1;
		border-radius: var(--radius-sm);
		display: flex;
		align-items: flex-end;
		padding: 6px 8px;
		font: 500 12px / 1 var(--font-sans);
		color: #0e1512;
	}
	.heat {
		display: flex;
		gap: 6px;
	}
	.heat span {
		width: 32px;
		height: 32px;
		border-radius: 50%;
	}
	.heat .none {
		box-shadow: inset 0 0 0 1px var(--data-band);
	}
	.type {
		min-height: 0;
		gap: 0;
	}
	.type-row {
		display: grid;
		grid-template-columns: 7rem minmax(0, 1fr) 6rem;
		gap: var(--space-5);
		align-items: baseline;
		padding: var(--space-3) 0;
		box-shadow: inset 0 -1px 0 var(--surface-raised);
	}
	.type-row span {
		white-space: nowrap;
		overflow: hidden;
		text-overflow: ellipsis;
	}
	.type-row code:last-child {
		text-align: right;
	}
	.row {
		display: flex;
		flex-wrap: wrap;
		gap: var(--space-2);
		align-items: center;
	}
	.col {
		display: flex;
		flex-direction: column;
		align-items: flex-start;
		gap: var(--space-3);
	}
	.col :global(.status-pill) {
		margin-top: 0;
	}
	.metric {
		display: flex;
		align-items: baseline;
		gap: 6px;
	}
	@media (max-width: 640px) {
		.type-row {
			grid-template-columns: 1fr;
			gap: var(--space-1);
		}
		.type-row code:last-child {
			text-align: left;
		}
	}
</style>
