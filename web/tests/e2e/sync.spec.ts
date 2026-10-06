// web/tests/e2e/sync.spec.ts
import { test, expect, type Page } from '@playwright/test';
import http from 'node:http';

const STUB_PORT = 8791;

function startSyncStub(): Promise<http.Server> {
	let backfillTriggered = false;
	let pollCount = 0;
	// counted only from the trigger POST onward, so the number of pre-trigger
	// status polls (varies with test setup/reload timing) never shifts when
	// the job flips from running to done -- a prior version of this stub used
	// the raw poll count and flaked because of that.
	let pollsSinceTrigger = 0;
	const server = http.createServer((req, res) => {
		if (req.method === 'GET' && req.url === '/api/connections') {
			res.writeHead(200, { 'Content-Type': 'application/json' });
			res.end(
				JSON.stringify({
					connections: [
						{ connector: 'garmin', status: 'active', external_account: 'user@example.com' }
					]
				})
			);
			return;
		}
		if (req.method === 'GET' && req.url === '/api/sync/status') {
			pollCount += 1;
			if (backfillTriggered) pollsSinceTrigger += 1;
			// stays "running" for several poll ticks so a test has a comfortable
			// window to assert on the running/disabled state before it flips
			const status = !backfillTriggered ? [] : pollsSinceTrigger < 5 ? 'running' : 'done';
			res.writeHead(200, { 'Content-Type': 'application/json' });
			res.end(
				JSON.stringify({
					jobs: !backfillTriggered
						? []
						: [
								{
									job_id: 'job-1',
									connector: 'garmin',
									kind: 'hr_intraday',
									from_date: '2025-06-01',
									to_date: '2026-09-08',
									status,
									windows_processed: pollCount,
									windows_total: 100,
									error: null,
									started_at: '2026-09-08T10:00:00Z',
									finished_at: status === 'done' ? '2026-09-08T10:05:00Z' : null
								}
							]
				})
			);
			return;
		}
		if (req.method === 'POST' && req.url === '/api/sync/garmin/backfill') {
			backfillTriggered = true;
			req.resume();
			req.on('end', () => {
				res.writeHead(202, { 'Content-Type': 'application/json' });
				res.end(
					JSON.stringify({
						jobs: [
							{
								job_id: 'job-1',
								connector: 'garmin',
								kind: 'hr_intraday',
								from_date: '2025-06-01',
								to_date: '2026-09-08',
								status: 'queued',
								windows_processed: 0,
								windows_total: 100,
								error: null,
								started_at: '2026-09-08T10:00:00Z',
								finished_at: null
							}
						]
					})
				);
			});
			return;
		}
		res.writeHead(404).end();
	});
	return new Promise((resolve, reject) => {
		server.once('error', reject);
		server.listen(STUB_PORT, () => resolve(server));
	});
}

test.describe('sync page', () => {
	let stub: http.Server | undefined;

	test.beforeEach(async ({ context }) => {
		await context.addCookies([
			{ name: 'session_id', value: 'e2e-fake-session', domain: 'localhost', path: '/' }
		]);
		stub = await startSyncStub();
	});

	test.afterEach(async () => {
		if (stub) await new Promise<void>((resolve) => stub!.close(() => resolve()));
		stub = undefined;
	});

	// the Garmin/calendar triggers live in the "Sync starten" dropdown since e983988
	async function openSyncMenu(page: Page) {
		await page.getByRole('button', { name: /Sync starten/ }).click();
	}

	test('trigger button starts a backfill and polling shows progress to done', async ({ page }) => {
		await page.goto('/sync', { waitUntil: 'networkidle' });
		await openSyncMenu(page);
		await page.locator('button', { hasText: 'Garmin-Backfill starten' }).click();
		await expect(page.getByText('running')).toBeVisible({ timeout: 5000 });
		await expect(page.getByText('done')).toBeVisible({ timeout: 15000 });
	});

	test('trigger button stays disabled while a job is active, including across a reload, and re-enables when done', async ({
		page
	}) => {
		await page.goto('/sync', { waitUntil: 'networkidle' });
		await openSyncMenu(page);
		const button = page.locator('button', { hasText: /Backfill/ });
		await expect(button).toBeEnabled();

		await button.click();
		await expect(page.getByText('running')).toBeVisible({ timeout: 5000 });
		await expect(button).toBeDisabled();
		await expect(button).toHaveText('Garmin-Backfill läuft …');

		// the disabled state must come from server-reported job status (data.jobs),
		// not from local click-handler state -- reload and confirm it survives
		await page.reload({ waitUntil: 'networkidle' });
		await openSyncMenu(page);
		await expect(page.locator('button', { hasText: /Backfill/ })).toBeDisabled();

		await expect(page.getByText('done')).toBeVisible({ timeout: 15000 });
		await expect(page.locator('button', { hasText: /Backfill/ })).toBeEnabled();
		await expect(page.locator('button', { hasText: /Backfill/ })).toHaveText(
			'Garmin-Backfill starten'
		);
	});

	test('shows a progress indicator while a job is running', async ({ page }) => {
		await page.goto('/sync', { waitUntil: 'networkidle' });
		await openSyncMenu(page);
		await page.locator('button', { hasText: 'Garmin-Backfill starten' }).click();
		await expect(page.getByText('running')).toBeVisible({ timeout: 5000 });
		await expect(page.locator('progress')).toBeVisible();
		await expect(page.locator('.progress-label')).toContainText('/ 100');
	});
});
