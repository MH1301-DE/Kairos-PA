// web/tests/e2e/sync.spec.ts
import { test, expect } from '@playwright/test';
import http from 'node:http';

const STUB_PORT = 8791;

function startSyncStub(): Promise<http.Server> {
	let backfillTriggered = false;
	let pollCount = 0;
	const server = http.createServer((req, res) => {
		if (req.method === 'GET' && req.url === '/api/connections') {
			res.writeHead(200, { 'Content-Type': 'application/json' });
			res.end(
				JSON.stringify({
					connections: [{ connector: 'garmin', status: 'active', external_account: 'user@example.com' }]
				})
			);
			return;
		}
		if (req.method === 'GET' && req.url === '/api/sync/status') {
			pollCount += 1;
			const status = !backfillTriggered ? [] : pollCount < 3 ? 'running' : 'done';
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

	test('trigger button starts a backfill and polling shows progress to done', async ({ page }) => {
		await page.goto('/sync', { waitUntil: 'networkidle' });
		await page.locator('button', { hasText: 'Backfill starten' }).click();
		await expect(page.getByText('running')).toBeVisible({ timeout: 5000 });
		await expect(page.getByText('done')).toBeVisible({ timeout: 10000 });
	});
});
