// Scheduler page helpers: UI presets <-> the backend's cron subset, JSON schema -> form fields

export interface SchedulerAction {
	name: string;
	label: string;
	description: string;
	schema: JsonSchema;
	min_interval_s: number;
}

export interface JobStep {
	action: string;
	params: Record<string, unknown>;
}

export interface SchedulerJob {
	id: string;
	name: string;
	label: string;
	timezone: string;
	enabled: boolean;
	next_run_at: string | null;
	last_status: RunStatus | null;
	last_run_at: string | null;
	last_success_at: string | null;
	running: boolean;
	conversation_id: string | null;
	consecutive_failures: number;
	proposal_open: boolean;
	// action names in the list, full steps when a single job is loaded
	steps: string[] | JobStep[];
	cron_exprs?: string[];
	context_reset_every?: number;
}

export type RunStatus = 'running' | 'ok' | 'failed' | 'skipped' | 'interrupted';

export interface StepResult {
	action: string;
	status: 'ok' | 'skipped' | 'failed' | 'not_run' | 'running';
	summary?: string | null;
	started_at?: string | null;
	finished_at?: string | null;
	error_code?: string | null;
	data?: Record<string, unknown>;
}

export interface JobRun {
	id: string;
	trigger: 'schedule' | 'catch_up' | 'manual';
	scheduled_for: string | null;
	started_at: string;
	finished_at: string | null;
	status: RunStatus;
	skip_reason: string | null;
	steps: StepResult[];
}

// --- presets ------------------------------------------------------------------------

export type Preset =
	| { kind: 'daily'; time: string }
	| { kind: 'weekdays'; time: string; days: number[] }
	| { kind: 'times'; times: string[] }
	| { kind: 'minutes'; every: number; from: number | null; to: number | null }
	| { kind: 'hours'; every: number; from: number | null; to: number | null };

export const MINUTE_STEPS = [15, 20, 30];
export const HOUR_STEPS = [1, 2, 3, 4, 6, 8, 12];
export const MAX_TIMES = 6;
// cron weekday numbers, Monday first as people read a week
export const WEEKDAYS: { value: number; label: string }[] = [
	{ value: 1, label: 'Mo' },
	{ value: 2, label: 'Di' },
	{ value: 3, label: 'Mi' },
	{ value: 4, label: 'Do' },
	{ value: 5, label: 'Fr' },
	{ value: 6, label: 'Sa' },
	{ value: 0, label: 'So' }
];

function splitTime(time: string): [number, number] {
	const [h, m] = time.split(':').map((part) => Number.parseInt(part, 10));
	return [h, m];
}

function pad(n: number): string {
	return String(n).padStart(2, '0');
}

function hourRange(from: number | null, to: number | null): string | null {
	return from !== null && to !== null ? `${from}-${to}` : null;
}

export function presetToCron(preset: Preset): string[] {
	switch (preset.kind) {
		case 'daily': {
			const [h, m] = splitTime(preset.time);
			return [`${m} ${h} * * *`];
		}
		case 'weekdays': {
			const [h, m] = splitTime(preset.time);
			const days = [...new Set(preset.days)].sort((a, b) => a - b);
			return [`${m} ${h} * * ${days.join(',')}`];
		}
		case 'times': {
			// same minute -> one expression with an hour list ("0 8,12,18 * * *")
			const byMinute = new Map<number, number[]>();
			for (const time of [...new Set(preset.times)].sort()) {
				const [h, m] = splitTime(time);
				byMinute.set(m, [...(byMinute.get(m) ?? []), h]);
			}
			return [...byMinute.entries()].map(([m, hours]) => `${m} ${hours.join(',')} * * *`);
		}
		case 'minutes':
			return [`*/${preset.every} ${hourRange(preset.from, preset.to) ?? '*'} * * *`];
		case 'hours': {
			const range = hourRange(preset.from, preset.to);
			return [`0 ${range ? `${range}/${preset.every}` : `*/${preset.every}`} * * *`];
		}
	}
}

function numberList(field: string): number[] | null {
	const out: number[] = [];
	for (const item of field.split(',')) {
		const range = /^(\d+)-(\d+)$/.exec(item);
		if (range) {
			for (let n = Number(range[1]); n <= Number(range[2]); n++) out.push(n);
		} else if (/^\d+$/.test(item)) {
			out.push(Number(item));
		} else {
			return null;
		}
	}
	return out;
}

function parseRange(field: string): { from: number | null; to: number | null } | null {
	if (field === '*') return { from: null, to: null };
	const range = /^(\d+)-(\d+)$/.exec(field);
	return range ? { from: Number(range[1]), to: Number(range[2]) } : null;
}

// the server only accepts the subset the presets produce, so every stored job maps back
export function cronToPreset(exprs: string[]): Preset | null {
	const parts = exprs.map((e) => e.trim().split(/\s+/));
	if (parts.length === 0 || parts.some((p) => p.length !== 5 || p[2] !== '*' || p[3] !== '*')) {
		return null;
	}
	if (parts.length === 1) {
		const [minute, hour, , , weekday] = parts[0];
		const minuteStep = /^\*\/(\d+)$/.exec(minute);
		if (minuteStep && weekday === '*') {
			const range = parseRange(hour);
			return range ? { kind: 'minutes', every: Number(minuteStep[1]), ...range } : null;
		}
		const hourStep = /^(\*|\d+-\d+)\/(\d+)$/.exec(hour);
		if (hourStep && minute === '0' && weekday === '*') {
			const range = parseRange(hourStep[1]);
			return range ? { kind: 'hours', every: Number(hourStep[2]), ...range } : null;
		}
		if (weekday !== '*') {
			const days = numberList(weekday);
			if (!days || !/^\d+$/.test(minute) || !/^\d+$/.test(hour)) return null;
			return {
				kind: 'weekdays',
				time: `${pad(Number(hour))}:${pad(Number(minute))}`,
				days: [...new Set(days.map((d) => d % 7))].sort((a, b) => a - b)
			};
		}
	}
	const times: string[] = [];
	for (const [minute, hour, , , weekday] of parts) {
		const minutes = numberList(minute);
		const hours = numberList(hour);
		if (weekday !== '*' || !minutes || !hours) return null;
		for (const h of hours) for (const m of minutes) times.push(`${pad(h)}:${pad(m)}`);
	}
	times.sort();
	return times.length === 1 ? { kind: 'daily', time: times[0] } : { kind: 'times', times };
}

// --- JSON schema -> form fields -----------------------------------------------------

export interface JsonSchema {
	type?: string;
	title?: string;
	description?: string;
	enum?: (string | number)[];
	items?: JsonSchema;
	anyOf?: JsonSchema[];
	properties?: Record<string, JsonSchema>;
	required?: string[];
	default?: unknown;
	minimum?: number;
	maximum?: number;
	minLength?: number;
	maxLength?: number;
}

export interface FieldOption {
	value: string | null;
	label: string;
	disabled?: boolean;
}

export type FormField =
	| { kind: 'select'; name: string; label: string; hint: string; options: FieldOption[] }
	| { kind: 'multiselect'; name: string; label: string; hint: string; options: FieldOption[] }
	| {
			kind: 'text' | 'textarea';
			name: string;
			label: string;
			hint: string;
			required: boolean;
			maxLength: number | null;
	  }
	| {
			kind: 'number';
			name: string;
			label: string;
			hint: string;
			min: number | null;
			max: number | null;
			default: number | null;
	  };

export const OPTION_LABELS: Record<string, string> = {
	hr_intraday: 'Herzfrequenz',
	sleep: 'Schlaf',
	stress: 'Stress',
	body_battery: 'Body Battery',
	hrv: 'HRV',
	respiration: 'Atmung',
	spo2: 'SpO₂',
	daily_summary: 'Tageswerte',
	activity_list: 'Aktivitäten',
	activity_fit: 'Aktivitätsdateien',
	google_calendar: 'Google Kalender',
	caldav: 'Apple Kalender'
};

// the backend refuses these for now (Apple calendar arrives with the CalDAV spec)
export const UNAVAILABLE_OPTIONS = new Set(['caldav']);

function nonNull(schema: JsonSchema): { inner: JsonSchema; nullable: boolean } {
	const variants = schema.anyOf ?? [schema];
	const inner = variants.find((v) => v.type !== 'null') ?? schema;
	return { inner, nullable: variants.some((v) => v.type === 'null') };
}

function options(values: (string | number)[]): FieldOption[] {
	return values.map((v) => ({
		value: String(v),
		label: OPTION_LABELS[String(v)] ?? String(v),
		disabled: UNAVAILABLE_OPTIONS.has(String(v))
	}));
}

export function schemaToFields(schema: JsonSchema): FormField[] {
	const required = new Set(schema.required ?? []);
	return Object.entries(schema.properties ?? {}).map(([name, prop]): FormField => {
		const { inner, nullable } = nonNull(prop);
		const label = prop.title ?? name;
		const hint = prop.description ?? '';
		if (inner.type === 'array' && inner.items?.enum) {
			return { kind: 'multiselect', name, label, hint, options: options(inner.items.enum) };
		}
		if (inner.enum) {
			const opts = options(inner.enum);
			return {
				kind: 'select',
				name,
				label,
				hint,
				options: nullable ? [{ value: null, label: 'Standard' }, ...opts] : opts
			};
		}
		if (inner.type === 'integer' || inner.type === 'number') {
			return {
				kind: 'number',
				name,
				label,
				hint,
				min: inner.minimum ?? null,
				max: inner.maximum ?? null,
				default: typeof prop.default === 'number' ? prop.default : null
			};
		}
		const maxLength = inner.maxLength ?? null;
		return {
			kind: maxLength !== null && maxLength > 200 ? 'textarea' : 'text',
			name,
			label,
			hint,
			required: required.has(name),
			maxLength
		};
	});
}

// --- display ------------------------------------------------------------------------

export const STATUS_LABELS: Record<RunStatus, string> = {
	running: 'läuft',
	ok: 'ok',
	failed: 'fehlgeschlagen',
	skipped: 'übersprungen',
	interrupted: 'abgebrochen'
};

export const TRIGGER_LABELS: Record<JobRun['trigger'], string> = {
	schedule: 'geplant',
	catch_up: 'nachgeholt',
	manual: 'manuell'
};

export function statusTone(status: string | null): 'neutral' | 'attention' | 'deviation' {
	if (status === 'failed' || status === 'interrupted') return 'deviation';
	if (status === 'skipped') return 'attention';
	return 'neutral';
}

export const TEMPLATES: { name: string; label: string; preset: Preset; steps: JobStep[] }[] = [
	{
		name: 'Morgen-Briefing',
		label: 'Täglich 08:00',
		preset: { kind: 'daily', time: '08:00' },
		steps: [
			{ action: 'garmin.sync', params: {} },
			{ action: 'calendar.sync', params: {} },
			{
				action: 'agent.prompt',
				params: { prompt: 'Was gibt es Neues, was schlägst du für heute vor?' }
			}
		]
	},
	{
		name: 'Wochenanalyse',
		label: 'Sonntags 18:00',
		preset: { kind: 'weekdays', time: '18:00', days: [0] },
		steps: [
			{ action: 'garmin.sync', params: {} },
			{
				action: 'agent.prompt',
				params: {
					prompt:
						'Erstelle eine Wochenanalyse: Trainingslast, Erholung, Schlaf, Abgleich mit ' +
						'meinen Zielen, Empfehlung für die nächste Woche.'
				}
			}
		]
	}
];

export function relativeTime(iso: string, now: Date = new Date()): string {
	const minutes = Math.round((new Date(iso).getTime() - now.getTime()) / 60000);
	const abs = Math.abs(minutes);
	if (abs < 1) return 'jetzt';
	let text: string;
	if (abs < 60) text = `${abs} Min.`;
	else if (abs < 48 * 60) text = `${Math.round(abs / 60)} Std.`;
	else text = `${Math.round(abs / 1440)} Tagen`;
	return minutes > 0 ? `in ${text}` : `vor ${text}`;
}

export function formatLocal(iso: string, timeZone: string): string {
	return new Intl.DateTimeFormat('de-DE', {
		weekday: 'short',
		day: '2-digit',
		month: '2-digit',
		hour: '2-digit',
		minute: '2-digit',
		timeZone
	}).format(new Date(iso));
}
