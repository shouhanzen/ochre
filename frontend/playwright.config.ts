import { defineConfig, devices } from '@playwright/test'

const baseURL = process.env.OCHRE_BASE_URL ?? 'https://127.0.0.1:5173'

export default defineConfig({
  testDir: './e2e/tests',
  // Per-test artifacts (traces, screenshots, videos).
  // Keep this separate from the HTML report dir (Playwright will wipe the report dir).
  outputDir: './e2e/test-results',
  timeout: 60_000,
  expect: {
    timeout: 15_000,
  },
  reporter: [
    ['list'],
    ['html', { open: 'never', outputFolder: './e2e/playwright-report' }],
  ],
  use: {
    baseURL,
    ignoreHTTPSErrors: true,
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
    video: 'retain-on-failure',
    serviceWorkers: 'block',
  },
  projects: [
    {
      name: 'desktop-chromium',
      testMatch: /.*\.desktop\.spec\.ts/,
      use: { ...devices['Desktop Chrome'], browserName: 'chromium' },
    },
    {
      name: 'mobile-chromium',
      testMatch: /.*\.mobile\.spec\.ts/,
      // Use mobile emulation but keep Chromium so we only need Chromium installs.
      use: { ...devices['iPhone 14'], browserName: 'chromium' },
    },
  ],
})

