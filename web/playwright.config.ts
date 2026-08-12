import { defineConfig } from '@playwright/test';

export default defineConfig({
	webServer: {
		command: 'npm run dev',
		port: 5173,
		// keep the suite off port 8000 so it can run next to a live local backend
		env: { KAIROS_API_PROXY_TARGET: 'http://localhost:8791' }
	},
	testMatch: '**/*.{e2e,spec}.{ts,js}'
});
