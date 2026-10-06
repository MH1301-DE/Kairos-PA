<!-- web/src/lib/components/MetricTile.svelte -->
<script lang="ts">
	import { resolve } from '$app/paths';
	import Kachel from './Kachel.svelte';
	import InfoTooltip from './InfoTooltip.svelte';
	import type { ModuleDef, ModuleStatus } from '../modules';
	import { gaugeBandFor } from '../modules';
	import type { MetricResult } from '../types';
	import {
		kachelState,
		coverageFoot,
		gaugeGeometry,
		formatDuration,
		formatNumber,
		type TileInput
	} from '../kachel';
	import { hrZoneColors } from '../design/palette';

	let {
		tile,
		module,
		asOf,
		today,
		garminExpired = false,
		editing = false,
		onremove,
		onretry,
		onasof
	}: {
		tile: TileInput;
		module: ModuleDef;
		asOf: string;
		today: string;
		garminExpired?: boolean;
		editing?: boolean;
		onremove?: () => void;
		onretry?: () => void;
		onasof?: (date: string) => void;
	} = $props();

	let tileState = $derived(kachelState(tile, module));
	let r = $derived(tile.result as MetricResult);
	let dict = $derived((tile.result?.value ?? {}) as Record<string, number>);
	let status = $derived<ModuleStatus | null>(
		(tileState === 'ok' || tileState === 'teilweise') && module.status ? module.status(r) : null
	);
	let foot = $derived(
		tileState === 'ok' || tileState === 'teilweise' ? coverageFoot(r, module, tileState) : ''
	);

	let empty = $derived.by(() => {
		const res = tile.result;
		const need = res?.coverage_required_days ?? 0;
		const progress =
			res && need > 1 && res.coverage_days < need
				? ` Bisher: ${res.coverage_days} von ${need} ${module.coverageUnit === 'Nächte' ? 'Nächten' : 'Tagen'}.`
				: '';
		return {
			title: 'Noch nicht genug Daten',
			body: module.emptyHint + progress,
			action: { label: 'Jetzt abgleichen', href: resolve('/sync') }
		};
	});

	let error = $derived(
		garminExpired
			? {
					title: 'Garmin braucht eine neue Anmeldung',
					body: 'Seitdem kommen keine neuen Werte. Alles bis dahin bleibt erhalten.',
					action: { label: 'Bei Garmin anmelden', href: resolve('/onboarding') }
				}
			: {
					title: 'Daten gerade nicht verfügbar',
					body: 'Der Abruf ist fehlgeschlagen. Gespeicherte Werte bleiben erhalten.',
					action: onretry ? { label: 'Erneut versuchen', onclick: onretry } : undefined
				}
	);

	let askHref = $derived(`${resolve('/chat')}?q=${encodeURIComponent(module.askPrompt)}`);

	let dateInput: HTMLInputElement | undefined = $state();
	function openPicker() {
		if (!dateInput) return;
		// showPicker is missing in older Safari and jsdom
		if (typeof dateInput.showPicker === 'function') dateInput.showPicker();
		else dateInput.focus();
	}
	let periodLabel = $derived(
		asOf === today
			? module.period
			: `Stand ${new Date(asOf + 'T00:00:00').toLocaleDateString('de-DE')}`
	);

	const ZONE_RANGES = ['50–60 %', '60–70 %', '70–80 %', '80–90 %', '90–100 %'];
	let zones = $derived.by(() => {
		const keys = Object.keys(dict).sort();
		const max = Math.max(1, ...keys.map((k) => dict[k]));
		const colors = hrZoneColors();
		return keys.map((k, i) => ({
			id: `Z${i + 1}`,
			range: ZONE_RANGES[i] ?? '',
			time: formatDuration(dict[k]),
			width: `${((dict[k] / max) * 100).toFixed(1)}%`,
			color: colors[i] ?? colors[colors.length - 1]
		}));
	});
	let zoneTotal = $derived(Object.values(dict).reduce((a, b) => a + b, 0));

	let gauge = $derived.by(() => {
		if (module.kind !== 'gauge' || !module.gauge || !tile.result?.value) return null;
		const spec = module.gauge(r);
		const value = dict[spec.valueKey];
		if (value === undefined || !(spec.max > spec.min)) return null;
		const band = gaugeBandFor(spec, value);
		return { spec, value, band, geo: gaugeGeometry(spec, value) };
	});

	const num = (v: number | undefined, decimals = module.decimals ?? 1) =>
		v === undefined ? '–' : formatNumber(v, decimals).replace('-', '−');
</script>

{#snippet statusLine(s: ModuleStatus)}
	<span class="status-line {s.tone}"><span class="mark" aria-hidden="true"></span>{s.text}</span>
{/snippet}

{#snippet info()}
	<InfoTooltip lines={module.description} />
{/snippet}

{#snippet periodPicker()}
	<button type="button" class="period-btn" onclick={openPicker} class:pinned={asOf !== today}
		>{periodLabel}</button
	>
	<input
		bind:this={dateInput}
		class="date-input"
		type="date"
		value={asOf}
		max={today}
		aria-label="Stand von {module.title}"
		tabindex="-1"
		onchange={(e) => onasof?.(e.currentTarget.value)}
	/>
{/snippet}

<Kachel
	title={module.title}
	state={tileState}
	{foot}
	askHref={editing ? null : askHref}
	{empty}
	{error}
	{editing}
	{onremove}
	titleExtra={info}
	periodControl={periodPicker}
>
	{#if module.kind === 'gauge'}
		{#if gauge}
			<div class="gauge">
				<svg viewBox="0 0 120 100" class="dial" aria-hidden="true">
					{#if gauge.geo.band}<path class="band" d={gauge.geo.band} />{/if}
					<path class="track" d={gauge.geo.track} />
					{#if gauge.geo.value}
						<path class="value" class:partial={tileState === 'teilweise'} d={gauge.geo.value} />
					{/if}
				</svg>
				<div class="gauge-text">
					<div class="metric">
						<span class="t-metric-xl">{num(gauge.value, gauge.spec.decimals)}</span>
						{#if module.unit}<span class="t-unit">{module.unit}</span>{/if}
					</div>
					{@render statusLine({
						tone: gauge.band.tone,
						text: tileState === 'teilweise' ? `vorläufig · ${gauge.band.text}` : gauge.band.text
					})}
				</div>
			</div>
		{/if}
	{:else if module.kind === 'histogramm'}
		<div class="metric">
			<span class="t-metric-lg">{formatDuration(zoneTotal)}</span><span class="t-unit">Stunden</span
			>
		</div>
		<div class="zones">
			{#each zones as z (z.id)}
				<div class="zone-row">
					<span>{z.id}</span>
					<span class="faint">{z.range}</span>
					<span class="zone-track"
						><span style:width={z.width} style:background={z.color}></span></span
					>
					<span class="right">{z.time}</span>
				</div>
			{/each}
		</div>
	{:else if module.kind === 'belastung'}
		<div class="values">
			{#each module.fields ?? [] as f, i (f.key)}
				<div class="value-col">
					<span class="legend"
						><span class="legend-mark legend-{i}" aria-hidden="true"></span>{f.label}</span
					>
					<span class="value-row">
						<span class="t-metric-lg">{num(dict[f.key])}</span>
						{#if f.key === 'tsb' && status}{@render statusLine(status)}{/if}
					</span>
				</div>
			{/each}
		</div>
	{:else if module.fields}
		<div class="values">
			{#each module.fields as f, i (f.key)}
				<div class="value-col">
					<span class="legend">{f.label}</span>
					<span class="metric">
						<span class={i === 0 ? 't-metric-xl' : 't-metric-lg'}>{num(dict[f.key])}</span>
						{#if f.unit}<span class="t-unit">{f.unit}</span>{/if}
					</span>
				</div>
			{/each}
		</div>
		{#if status}{@render statusLine(status)}{/if}
	{:else}
		<div class="metric">
			<span class="t-metric-xl">{num(r.value as number)}</span>
			{#if module.unit}<span class="t-unit">{module.unit}</span>{/if}
		</div>
		{#if status}{@render statusLine(status)}{/if}
	{/if}
</Kachel>

<style>
	.metric {
		display: flex;
		align-items: baseline;
		gap: 6px;
	}

	.status-line {
		display: inline-flex;
		align-items: center;
		gap: var(--space-2);
		font: var(--type-body-sm);
		color: var(--status-neutral-text);
	}
	.status-line .mark {
		flex: none;
		width: 7px;
		height: 7px;
		border-radius: 50%;
		box-shadow: inset 0 0 0 1.5px var(--status-neutral-mark);
	}
	.status-line.attention {
		color: var(--status-attention-text);
	}
	.status-line.attention .mark {
		border-radius: 0;
		box-shadow: none;
		background: var(--status-attention-mark);
		transform: rotate(45deg);
	}
	.status-line.deviation {
		color: var(--status-deviation-text);
	}
	.status-line.deviation .mark {
		width: 0;
		height: 0;
		border-radius: 0;
		box-shadow: none;
		border-left: 4.5px solid transparent;
		border-right: 4.5px solid transparent;
		border-bottom: 8px solid var(--status-deviation-mark);
	}

	.period-btn {
		all: unset;
		cursor: pointer;
		border-radius: var(--radius-xs);
	}
	.period-btn:hover {
		color: var(--text-secondary);
	}
	.period-btn.pinned {
		color: var(--status-attention-text);
	}
	.period-btn:focus-visible {
		box-shadow: var(--shadow-focus);
	}
	/* kept in the DOM so showPicker() has an anchor, but never shown */
	.date-input {
		position: absolute;
		width: 1px;
		height: 1px;
		opacity: 0;
		pointer-events: none;
		right: var(--space-6);
		top: var(--space-6);
	}

	.gauge {
		flex: 1;
		display: flex;
		align-items: center;
		gap: var(--space-5);
	}
	.dial {
		width: 132px;
		height: 110px;
		flex: none;
		overflow: visible;
		fill: none;
	}
	.dial .band {
		stroke: var(--data-band);
		stroke-width: 3;
	}
	.dial .track {
		stroke: var(--data-track);
		stroke-width: 6;
		stroke-linecap: round;
	}
	.dial .value {
		stroke: var(--data-primary);
		stroke-width: 6;
		stroke-linecap: round;
	}
	/* a preliminary value is drawn dotted, same as the design's partial state */
	.dial .value.partial {
		stroke-dasharray: 2 5;
	}
	@media (max-width: 420px) {
		.gauge {
			gap: var(--space-3);
		}
		.dial {
			width: 96px;
			height: 80px;
		}
	}
	.gauge-text {
		display: flex;
		flex-direction: column;
		gap: var(--space-3);
		min-width: 0;
	}

	.zones {
		display: flex;
		flex-direction: column;
		gap: 9px;
	}
	.zone-row {
		display: grid;
		grid-template-columns: 26px 72px minmax(0, 1fr) 40px;
		gap: 10px;
		align-items: center;
		font: var(--type-caption);
		color: var(--text-secondary);
	}
	.zone-track {
		height: 12px;
		border-radius: 3px;
		background: var(--surface-raised);
		overflow: hidden;
	}
	.zone-track span {
		display: block;
		height: 100%;
		border-radius: 3px;
	}
	.faint {
		color: var(--text-faint);
	}
	.right {
		text-align: right;
	}

	.values {
		display: flex;
		flex-wrap: wrap;
		gap: var(--space-4) var(--space-10);
	}
	.value-col {
		display: flex;
		flex-direction: column;
		gap: var(--space-1);
	}
	.legend {
		display: flex;
		align-items: center;
		gap: var(--space-2);
		font: var(--type-body-sm);
		color: var(--text-muted);
	}
	.legend-mark {
		width: 14px;
		border-top: 2px solid var(--data-primary);
	}
	.legend-1 {
		border-top-style: dashed;
		border-top-color: var(--data-secondary);
	}
	.legend-2 {
		width: 10px;
		height: 8px;
		border-top: none;
		background: var(--data-band);
		border-radius: 1px;
	}
	.value-row {
		display: flex;
		align-items: baseline;
		gap: 14px;
		flex-wrap: wrap;
	}
</style>
