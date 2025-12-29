import { expect, test, type Page, type Request } from '@playwright/test'

let consoleLines: string[] = []
let failedReqs: string[] = []

test.beforeEach(async ({ page }) => {
  consoleLines = []
  failedReqs = []

  page.on('console', (m) => consoleLines.push(`[${m.type()}] ${m.text()}`))
  page.on('pageerror', (err) => consoleLines.push(`[pageerror] ${String((err as any)?.stack ?? err)}`))
  page.on('requestfailed', (req) => {
    const failure = req.failure()
    failedReqs.push(`${req.method()} ${req.url()} :: ${failure?.errorText ?? 'failed'}`)
  })
})

test.afterEach(async ({}, testInfo) => {
  await testInfo.attach('console.log', { body: consoleLines.join('\n') || '(no console output)\n', contentType: 'text/plain' })
  await testInfo.attach('requestfailed.log', { body: failedReqs.join('\n') || '(no failed requests)\n', contentType: 'text/plain' })
})

async function waitForSelectedSessionId(page: Page): Promise<string> {
  await page.waitForFunction(() => {
    try {
      const v = localStorage.getItem('ochre.selectedSessionId')
      return typeof v === 'string' && v.length > 0
    } catch {
      return false
    }
  })
  const sid = await page.evaluate(() => localStorage.getItem('ochre.selectedSessionId'))
  if (!sid) throw new Error('expected ochre.selectedSessionId to be set')
  return sid
}

async function resetLocalStorage(page: Page) {
  // IMPORTANT: don't use addInitScript(localStorage.clear) because it will also clear on reload.
  await page.goto('/')
  await page.evaluate(() => {
    try {
      localStorage.clear()
    } catch {
      // ignore
    }
  })
  await page.reload()
}

test('session selection persists across reload (desktop)', async ({ page }) => {
  await resetLocalStorage(page)

  await test.step('Load app and wait for initial session', async () => {
    const sid = await waitForSelectedSessionId(page)
    await expect(page.locator('.statusBar')).toContainText(`Session: ${sid.slice(0, 8)}`)
  })

  const sid0 = await waitForSelectedSessionId(page)

  await test.step('Open Sessions rail and create a new session', async () => {
    await page.getByTitle('Sessions').click()
    await expect(page.getByText('Sessions', { exact: true })).toBeVisible()
    await page.getByRole('button', { name: 'New' }).click()
    await page.waitForFunction(
      (prev) => {
        try {
          const cur = localStorage.getItem('ochre.selectedSessionId')
          return !!cur && cur !== prev
        } catch {
          return false
        }
      },
      sid0,
    )
  })

  const sid1 = await waitForSelectedSessionId(page)
  expect(sid1).not.toBe(sid0)

  await test.step('Reload and ensure no new session is created', async () => {
    let createCallsAfterReload = 0
    const onReq = (r: Request) => {
      if (r.method() === 'POST' && r.url().includes('/api/sessions')) createCallsAfterReload += 1
    }

    page.on('request', onReq)
    await page.reload()

    const sidAfter = await waitForSelectedSessionId(page)
    expect(sidAfter).toBe(sid1)

    await page.waitForTimeout(800)
    page.off('request', onReq)
    expect(createCallsAfterReload, 'expected no POST /api/sessions after reload').toBe(0)
  })

  await test.step('Verify the selected session row is highlighted', async () => {
    await page.getByTitle('Sessions').click()
    await expect(page.locator(`.treeRow.selected[title="${sid1}"]`)).toBeVisible()
  })
})

