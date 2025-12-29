import { expect, test, type Page } from '@playwright/test'

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

test('session selection persists across reload (mobile)', async ({ page }) => {
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

  await test.step('Load app and wait for initial session', async () => {
    await expect(page.getByText('Ochre', { exact: true })).toBeVisible()
    await waitForSelectedSessionId(page)
  })

  const sid0 = await waitForSelectedSessionId(page)

  await test.step('Browse → Sessions → New session (lands back in Chat)', async () => {
    await page.locator('.mobileTabBar').getByRole('button', { name: 'Browse' }).click()
    await page.locator('.mobileBrowseToggle').getByRole('button', { name: 'Sessions' }).click()
    await expect(page.locator('.panelTitle').filter({ hasText: 'Sessions' })).toBeVisible()

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

    // App switches back to Chat tab after selecting a session.
    await expect(page.locator('.mobileSubtitle')).toHaveText('Chat')
    await expect(page.locator('.chatComposer')).toBeVisible()
  })

  const sid1 = await waitForSelectedSessionId(page)
  expect(sid1).not.toBe(sid0)

  await test.step('Reload and verify persisted session id', async () => {
    await page.reload()
    const sidAfter = await waitForSelectedSessionId(page)
    expect(sidAfter).toBe(sid1)
  })

  await test.step('Browse → Sessions shows persisted session as selected', async () => {
    await page.locator('.mobileTabBar').getByRole('button', { name: 'Browse' }).click()
    await page.locator('.mobileBrowseToggle').getByRole('button', { name: 'Sessions' }).click()
    await expect(page.locator(`.treeRow.selected[title="${sid1}"]`)).toBeVisible()
  })
})

