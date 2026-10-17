import { describe, expect, it } from 'vitest';
import {
	cronToPreset,
	presetToCron,
	schemaToFields,
	statusTone,
	TEMPLATES,
	type JsonSchema,
	type Preset
} from '../../src/lib/scheduler';
import { historyToItems } from '../../src/lib/chat/transcript';
import type { ChatMessage } from '../../src/lib/types';

describe('presets <-> cron', () => {
	const cases: [Preset, string[]][] = [
		[{ kind: 'daily', time: '08:00' }, ['0 8 * * *']],
		[{ kind: 'daily', time: '07:30' }, ['30 7 * * *']],
		[{ kind: 'weekdays', time: '18:00', days: [0, 5] }, ['0 18 * * 0,5']],
		[{ kind: 'weekdays', time: '06:45', days: [1, 2, 3, 4, 5] }, ['45 6 * * 1,2,3,4,5']],
		[{ kind: 'times', times: ['08:00', '12:00', '18:00'] }, ['0 8,12,18 * * *']],
		[{ kind: 'times', times: ['08:00', '19:30'] }, ['0 8 * * *', '30 19 * * *']],
		[{ kind: 'minutes', every: 15, from: null, to: null }, ['*/15 * * * *']],
		[{ kind: 'minutes', every: 30, from: 8, to: 20 }, ['*/30 8-20 * * *']],
		[{ kind: 'hours', every: 2, from: null, to: null }, ['0 */2 * * *']],
		[{ kind: 'hours', every: 2, from: 8, to: 20 }, ['0 8-20/2 * * *']]
	];

	it.each(cases)('%o maps to cron and back', (preset, exprs) => {
		expect(presetToCron(preset)).toEqual(exprs);
		expect(cronToPreset(exprs)).toEqual(preset);
	});

	it('normalises duplicates and order', () => {
		expect(presetToCron({ kind: 'times', times: ['18:00', '08:00', '08:00'] })).toEqual([
			'0 8,18 * * *'
		]);
		expect(cronToPreset(['0 18 * * 7'])).toEqual({ kind: 'weekdays', time: '18:00', days: [0] });
		expect(cronToPreset(['0 18 * * 1-5'])).toEqual({
			kind: 'weekdays',
			time: '18:00',
			days: [1, 2, 3, 4, 5]
		});
	});

	it('rejects what the presets cannot express', () => {
		expect(cronToPreset([])).toBeNull();
		expect(cronToPreset(['0 8 1 * *'])).toBeNull();
		expect(cronToPreset(['*/15 * * * 1'])).toBeNull();
		expect(cronToPreset(['0 8'])).toBeNull();
	});

	it('templates are expressible', () => {
		expect(TEMPLATES.map((t) => presetToCron(t.preset))).toEqual([['0 8 * * *'], ['0 18 * * 0']]);
		expect(TEMPLATES[0].steps.map((s) => s.action)).toEqual([
			'garmin.sync',
			'calendar.sync',
			'agent.prompt'
		]);
	});
});

describe('schema -> form fields', () => {
	it('maps the four action schemas', () => {
		const garmin: JsonSchema = {
			properties: {
				kinds: {
					anyOf: [
						{ type: 'array', items: { type: 'string', enum: ['sleep', 'hrv'] } },
						{ type: 'null' }
					],
					default: null,
					title: 'Datenarten',
					description: 'leer = alle Datenarten'
				}
			}
		};
		const calendar: JsonSchema = {
			properties: {
				calendar: {
					anyOf: [{ type: 'string', enum: ['google_calendar', 'caldav'] }, { type: 'null' }],
					title: 'Kalender'
				}
			}
		};
		const recompute: JsonSchema = {
			properties: {
				days: { type: 'integer', minimum: 1, maximum: 730, default: 60, title: 'Tage' }
			}
		};
		const agent: JsonSchema = {
			properties: { prompt: { type: 'string', minLength: 1, maxLength: 2000, title: 'Frage' } },
			required: ['prompt']
		};

		expect(schemaToFields(garmin)).toEqual([
			{
				kind: 'multiselect',
				name: 'kinds',
				label: 'Datenarten',
				hint: 'leer = alle Datenarten',
				options: [
					{ value: 'sleep', label: 'Schlaf', disabled: false },
					{ value: 'hrv', label: 'HRV', disabled: false }
				]
			}
		]);
		const [cal] = schemaToFields(calendar);
		expect(cal.kind).toBe('select');
		expect(cal.kind === 'select' && cal.options).toEqual([
			{ value: null, label: 'Standard' },
			{ value: 'google_calendar', label: 'Google Kalender', disabled: false },
			{ value: 'caldav', label: 'Apple Kalender', disabled: true }
		]);
		expect(schemaToFields(recompute)).toEqual([
			{ kind: 'number', name: 'days', label: 'Tage', hint: '', min: 1, max: 730, default: 60 }
		]);
		expect(schemaToFields(agent)).toEqual([
			{
				kind: 'textarea',
				name: 'prompt',
				label: 'Frage',
				hint: '',
				required: true,
				maxLength: 2000
			}
		]);
	});

	it('short strings become a single-line input', () => {
		const [field] = schemaToFields({ properties: { name: { type: 'string', maxLength: 80 } } });
		expect(field.kind).toBe('text');
	});
});

describe('status and chat divider', () => {
	it('uses shape tones, failed is a deviation', () => {
		expect(statusTone('ok')).toBe('neutral');
		expect(statusTone('skipped')).toBe('attention');
		expect(statusTone('failed')).toBe('deviation');
		expect(statusTone(null)).toBe('neutral');
	});

	function msg(seq: number, role: ChatMessage['role'], content: string): ChatMessage {
		return {
			id: `m${seq}`,
			seq,
			role,
			content,
			tool_calls: null,
			tool_call_id: null,
			tool_name: null,
			created_at: '2026-10-15T06:00:00Z'
		};
	}

	it('draws one divider after the reset boundary', () => {
		const items = historyToItems(
			[
				msg(1, 'user', 'a'),
				msg(2, 'assistant', 'b'),
				msg(5, 'user', 'c'),
				msg(6, 'assistant', 'd')
			],
			2
		);
		expect(items.map((i) => i.kind)).toEqual(['user', 'assistant', 'divider', 'user', 'assistant']);
	});

	it('no divider without a boundary or when nothing follows it', () => {
		expect(historyToItems([msg(1, 'user', 'a')], null).some((i) => i.kind === 'divider')).toBe(
			false
		);
		expect(historyToItems([msg(1, 'user', 'a')], 1).some((i) => i.kind === 'divider')).toBe(false);
	});
});

describe('relative time', () => {
	const now = new Date('2026-10-15T06:00:00Z');
	it('formats past and future in German', async () => {
		const { relativeTime } = await import('../../src/lib/scheduler');
		expect(relativeTime('2026-10-15T06:00:20Z', now)).toBe('jetzt');
		expect(relativeTime('2026-10-15T06:45:00Z', now)).toBe('in 45 Min.');
		expect(relativeTime('2026-10-15T03:00:00Z', now)).toBe('vor 3 Std.');
		expect(relativeTime('2026-10-18T06:00:00Z', now)).toBe('in 3 Tagen');
	});
});
