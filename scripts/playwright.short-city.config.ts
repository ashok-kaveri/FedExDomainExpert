import { defineConfig, devices } from '/Users/ashokkumarn/Documents/Pluginhive/fedex-test-automation/node_modules/@playwright/test';
import * as dotenv from '/Users/ashokkumarn/Documents/Pluginhive/fedex-test-automation/node_modules/dotenv/lib/main.js';

dotenv.config({ path: '/Users/ashokkumarn/Documents/Pluginhive/fedex-test-automation/.env', quiet: true });

export default defineConfig({
  testDir: '/Users/ashokkumarn/Documents/Pluginhive/AILearning/FedExDomainExpert/scripts',
  testMatch: /short_city_repo_native\.spec\.ts/,
  fullyParallel: false,
  workers: 1,
  reporter: [['list']],
  use: {
    trace: 'on-first-retry',
    acceptDownloads: true,
    launchOptions: {
      args: ['--disable-blink-features=AutomationControlled'],
    },
    viewport: { width: 1400, height: 1000 },
  },
  projects: [
    {
      name: 'Google Chrome',
      use: {
        ...devices['Desktop Chrome'],
        channel: 'chrome',
        viewport: { width: 1400, height: 1000 },
        storageState: '/Users/ashokkumarn/Documents/Pluginhive/fedex-test-automation/auth.json',
      },
    },
  ],
});
