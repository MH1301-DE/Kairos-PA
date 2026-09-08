import { defineConfig } from '@playwright/test';

export default defineConfig({
	// e2e specs stub the backend on a fixed port (8791, see onboarding.spec.ts
	// and sync.spec.ts) rather than a per-file random one; running spec files
	// concurrently races two stub servers for that same port (EADDRINUSE).
	// Serial execution keeps one stub bound at a time.
	workers: 1,
	webServer: {
		command: 'npm run dev',
		port: 5173,
		// keep the suite off port 8000 so it can run next to a live local backend
		env: { KAIROS_API_PROXY_TARGET: 'http://localhost:8791' },
		// a reused dev server would keep its own proxy target (likely :8000), which
		// wouldn't match the stub on :8791 — always start a fresh one for this env
		reuseExistingServer: false
	},
	testMatch: '**/*.{e2e,spec}.{ts,js}'
});
