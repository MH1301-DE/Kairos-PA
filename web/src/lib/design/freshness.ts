import type { ConnectionInfo, SyncJob } from '../types';

export type FreshnessState = 'aktuell' | 'laeuft' | 'veraltet' | 'abgelaufen';

export interface Freshness {
	state: FreshnessState;
	label: string;
}

const STALE_AFTER_MS = 6 * 60 * 60 * 1000;

function clock(d: Date): string {
	return d.toLocaleTimeString('de-DE', { hour: '2-digit', minute: '2-digit' });
}

function dayLabel(d: Date, now: Date): string {
	const startOf = (x: Date) => new Date(x.getFullYear(), x.getMonth(), x.getDate()).getTime();
	const days = Math.round((startOf(now) - startOf(d)) / 86_400_000);
	if (days === 0) return 'heute';
	if (days === 1) return 'gestern';
	return `${d.toLocaleDateString('de-DE', { day: 'numeric', month: 'numeric' })}`;
}

// the header indicator grows with risk: current < syncing < stale < expired
export function freshness(
	garmin: ConnectionInfo | undefined,
	jobs: SyncJob[],
	now: Date = new Date()
): Freshness | null {
	if (!garmin) return null;
	if (garmin.status === 'reauth_required') {
		return { state: 'abgelaufen', label: 'Garmin-Anmeldung abgelaufen' };
	}
	const running = jobs.filter((j) => j.connector === 'garmin' && j.status === 'running');
	if (running.length > 0) {
		const done = running.reduce((n, j) => n + j.windows_processed, 0);
		const total = running.reduce((n, j) => n + (j.windows_total ?? 0), 0);
		return {
			state: 'laeuft',
			label: total > 0 ? `Abgleich läuft · ${done} von ${total}` : 'Abgleich läuft'
		};
	}
	if (!garmin.last_ok_at) {
		return { state: 'veraltet', label: 'Garmin noch nicht abgeglichen' };
	}
	const last = new Date(garmin.last_ok_at);
	if (now.getTime() - last.getTime() > STALE_AFTER_MS) {
		return { state: 'veraltet', label: `Garmin-Stand von ${dayLabel(last, now)}, ${clock(last)}` };
	}
	return { state: 'aktuell', label: `aktuell · ${clock(last)}` };
}
