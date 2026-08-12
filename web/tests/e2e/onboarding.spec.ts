// web/tests/e2e/onboarding.spec.ts
import { test, expect } from '@playwright/test';
import http from 'node:http';

// The onboarding form (Task 10) uses `use:enhance`, which posts to the page
// itself. That request is handled server-side by `+page.server.ts`'s action,
// which calls `apiPost` from inside the Node dev-server process — a real
// server-to-server HTTP call through Vite's `/api` proxy (see vite.config.ts)
// that never touches the browser's network stack. `page.route()` only
// intercepts requests the browser makes directly, so it cannot see or mock
// this call. Instead we stand up a real HTTP server on port 8000 — the exact
// port `server.proxy` in vite.config.ts forwards `/api` requests to — and let
// the proxy hop land on it for real.
function startGarminStub(
	responder: (callCount: number) => { status: number; body: unknown }
): Promise<http.Server> {
	let callCount = 0;
	const server = http.createServer((req, res) => {
		if (req.method !== 'POST' || req.url !== '/api/connections/garmin') {
			res.writeHead(404).end();
			return;
		}
		const chunks: Buffer[] = [];
		req.on('data', (chunk: Buffer) => chunks.push(chunk));
		req.on('end', () => {
			callCount += 1;
			const { status, body } = responder(callCount);
			res.writeHead(status, { 'Content-Type': 'application/json' });
			res.end(JSON.stringify(body));
		});
	});
	return new Promise((resolve, reject) => {
		server.once('error', reject);
		server.listen(8000, () => resolve(server));
	});
}

function closeStub(server: http.Server | undefined): Promise<void> {
	if (!server) return Promise.resolve();
	return new Promise((resolve) => server.close(() => resolve()));
}

test.describe('onboarding', () => {
	let stub: http.Server | undefined;

	test.beforeEach(async ({ context }) => {
		// hooks.server.ts requires a session cookie to reach any non-public route
		await context.addCookies([
			{ name: 'session_id', value: 'e2e-fake-session', domain: 'localhost', path: '/' }
		]);
	});

	test.afterEach(async () => {
		// always release port 8000, even on assertion failure, so a real
		// backend (or the next test's stub) can bind it
		await closeStub(stub);
		stub = undefined;
	});

	test('shows an error on invalid credentials', async ({ page }) => {
		stub = await startGarminStub(() => ({
			status: 401,
			body: { detail: 'invalid_credentials' }
		}));
		await page.goto('/onboarding');
		await page.fill('input[name=email]', 'wrong@example.com');
		await page.fill('input[name=password]', 'wrongpass');
		// scoped to the onboarding form: the layout nav also renders a
		// `button[type=submit]` (the logout form), so an unscoped selector
		// is ambiguous and can click the wrong button
		await page.locator('main form button[type=submit]').click();
		await expect(page.getByText('E-Mail oder Passwort falsch.')).toBeVisible();
	});

	test('shows the MFA field on a 202 response, then succeeds', async ({ page }) => {
		stub = await startGarminStub((callCount) =>
			callCount === 1
				? { status: 202, body: { status: 'mfa_required' } }
				: { status: 201, body: { status: 'connected' } }
		);
		await page.goto('/onboarding');
		await page.fill('input[name=email]', 'user@example.com');
		await page.fill('input[name=password]', 'correctpass');
		await page.locator('main form button[type=submit]').click();
		await expect(page.locator('input[name=mfa_token]')).toBeVisible();
		await page.fill('input[name=mfa_token]', '123456');
		await page.locator('main form button[type=submit]').click();
		await expect(page.getByText(/Verbunden mit/)).toBeVisible();
	});
});
