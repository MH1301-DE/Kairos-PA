import { describe, it, expect } from 'vitest';
import { render, screen } from '@testing-library/svelte';
import ChatChart from '../src/lib/chat/ChatChart.svelte';
import Markdown from '../src/lib/chat/Markdown.svelte';

describe('ChatChart', () => {
	it('renders a StatCard as label/value pairs', () => {
		render(ChatChart, {
			component: 'StatCard',
			config: { title: 'Heute', items: [{ label: 'Ruhepuls', value: 52, unit: 'bpm' }] }
		});
		expect(screen.getByText('Heute')).toBeTruthy();
		expect(screen.getByText('Ruhepuls')).toBeTruthy();
		expect(screen.getByText('52 bpm')).toBeTruthy();
	});

	it('renders a Table as an HTML table', () => {
		const { container } = render(ChatChart, {
			component: 'Table',
			config: { title: 'Woche', columns: ['Tag', 'km'], rows: [['Mo', 5]] }
		});
		expect(container.querySelectorAll('th')).toHaveLength(2);
		expect(screen.getByText('Mo')).toBeTruthy();
	});

	it('renders chart components through ECharts as svg', () => {
		const { container } = render(ChatChart, {
			component: 'TimeSeriesChart',
			config: { title: 'HRV', unit: 'ms', points: [{ date: '2026-10-01', value: 50 }] }
		});
		expect(container.querySelector('svg')).toBeTruthy();
	});
});

describe('Markdown', () => {
	it('renders markdown and strips scripts', () => {
		const { container } = render(Markdown, {
			text: '**fett** <img src=x onerror="alert(1)"><script>alert(1)</script>'
		});
		expect(container.querySelector('strong')?.textContent).toBe('fett');
		expect(container.querySelector('script')).toBeNull();
		expect(container.querySelector('img')?.getAttribute('onerror')).toBeNull();
	});
});
