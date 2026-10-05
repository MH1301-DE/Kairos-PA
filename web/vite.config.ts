import { defineConfig } from 'vitest/config';
import { playwright } from '@vitest/browser-playwright';
import adapter from '@sveltejs/adapter-node';
import { sveltekit } from '@sveltejs/kit/vite';
import { SvelteKitPWA } from '@vite-pwa/sveltekit';

// overridable so the E2E suite can point the proxy at its own stub port
// instead of colliding with a locally running backend on 8000
const apiProxyTarget = process.env.KAIROS_API_PROXY_TARGET ?? 'http://localhost:8000';

export default defineConfig({
	plugins: [
		sveltekit({
			compilerOptions: {
				// Force runes mode for the project, except for libraries. Can be removed in svelte 6.
				runes: ({ filename }) =>
					filename.split(/[/\\]/).includes('node_modules') ? undefined : true
			},
			adapter: adapter()
		}),
		SvelteKitPWA({
			registerType: 'autoUpdate',
			// SvelteKit builds with vite base './', which would emit a relative
			// manifest/sw href and 404 on every nested route (/sync, /onboarding)
			base: '/',
			scope: '/',
			manifest: {
				name: 'Kairos',
				short_name: 'Kairos',
				description: 'Persönlicher Gesundheits- und Trainingsassistent',
				theme_color: '#0e1512',
				background_color: '#0e1512',
				display: 'standalone',
				icons: [
					{ src: '/icons/icon-192.png', sizes: '192x192', type: 'image/png' },
					{ src: '/icons/icon-512.png', sizes: '512x512', type: 'image/png' }
				]
			},
			workbox: {
				// app-shell caching only — dashboard data always requires a live
				// backend connection, per the design spec's explicit no-offline-sync decision
				globPatterns: ['**/*.{js,css,html,svg,png,ico}']
			}
		})
	],
	server: {
		proxy: {
			'/api': { target: apiProxyTarget, changeOrigin: true },
			'/auth': { target: apiProxyTarget, changeOrigin: true }
		}
	},
	test: {
		expect: { requireAssertions: true },
		globals: true,
		projects: [
			{
				extends: './vite.config.ts',
				test: {
					name: 'client',
					browser: {
						enabled: true,
						provider: playwright(),
						instances: [{ browser: 'chromium', headless: true }]
					},
					include: ['src/**/*.svelte.{test,spec}.{js,ts}'],
					exclude: ['src/lib/server/**']
				}
			},

			{
				extends: './vite.config.ts',
				resolve: { conditions: ['browser'] },
				test: {
					name: 'server',
					environment: 'jsdom',
					setupFiles: ['./tests/setup-jsdom.ts'],
					include: ['src/**/*.{test,spec}.{js,ts}', 'tests/**/*.{test,spec}.{js,ts}'],
					// tests/e2e runs under Playwright, not vitest — its test.describe() call
					// throws when collected outside a Playwright runner
					exclude: ['src/**/*.svelte.{test,spec}.{js,ts}', 'tests/e2e/**']
				}
			}
		]
	}
});
