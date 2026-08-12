import { describe, it, expect } from 'vitest';
import { render, screen } from '@testing-library/svelte';
import ConfidenceBadge from '../../src/lib/components/ConfidenceBadge.svelte';

describe('ConfidenceBadge', () => {
	it('renders nothing visible for high confidence', () => {
		render(ConfidenceBadge, { confidence: 'high' });
		expect(screen.queryByTestId('confidence-badge')).toBeNull();
	});

	it('renders a badge for medium confidence', () => {
		render(ConfidenceBadge, { confidence: 'medium' });
		expect(screen.getByTestId('confidence-badge').textContent).toContain('mittel');
	});

	it('renders a badge for low confidence', () => {
		render(ConfidenceBadge, { confidence: 'low' });
		expect(screen.getByTestId('confidence-badge').textContent).toContain('niedrig');
	});
});
