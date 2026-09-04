import { defineConfig, devices } from '@playwright/test'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const repository = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..')
const python = process.env.AUTODEPLOY_TEST_PYTHON || (process.platform === 'win32' ? 'python' : path.join(repository, '.venv/bin/python'))
const reuseExternalServer = process.env.AUTODEPLOY_E2E_REUSE_SERVER === 'true'

export default defineConfig({
  testDir: './e2e',
  timeout: 30_000,
  expect: { timeout: 8_000 },
  fullyParallel: false,
  retries: process.env.CI ? 1 : 0,
  reporter: process.env.CI ? [['html', { open: 'never' }], ['list']] : 'list',
  use: {
    baseURL: 'http://127.0.0.1:8899',
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
    ...devices['Desktop Chrome'],
  },
  webServer: {
    command: `"${python}" -m webapp`,
    cwd: repository,
    url: 'http://127.0.0.1:8899/api/v1/health',
    // Lets CI/containerized browsers exercise a server started by the host
    // Python environment without requiring Python dependencies in the browser
    // image. Normal local runs still start a fresh isolated server.
    reuseExistingServer: reuseExternalServer,
    timeout: 30_000,
    env: {
      ...process.env,
      AUTODEPLOY_HOST: '127.0.0.1',
      AUTODEPLOY_PORT: '8899',
      AUTODEPLOY_OPEN_BROWSER: 'false',
      AUTODEPLOY_OPENCODE_AUTO_CONNECT: 'false',
      AUTODEPLOY_DATA_DIR: '.e2e/data',
      AUTODEPLOY_ENV_FILE: '.e2e/.env',
      AUTODEPLOY_LOG_DIR: '.e2e/logs',
    },
  },
})
