import { expect, test, type Locator, type Page } from '@playwright/test'

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

async function expectHorizontallyInViewport(page: Page, el: Locator) {
  await expect(el).toBeVisible()
  const box = await el.boundingBox()
  expect(box, 'expected element to have a bounding box').not.toBeNull()

  const vp = page.viewportSize()
  expect(vp, 'expected viewport size to be set').not.toBeNull()
  const w = vp!.width

  // Allow a tiny epsilon for fractional rounding.
  expect(box!.x, 'expected element left edge to be inside viewport').toBeGreaterThanOrEqual(-1)
  expect(box!.x + box!.width, 'expected element right edge to be inside viewport').toBeLessThanOrEqual(w + 1)
}

test('mobile bottom tab bar keeps Chat/Pending visible after switching to Editor', async ({ page }) => {
  await page.goto('/')
  await expect(page.getByText('Ochre', { exact: true })).toBeVisible()

  const bar = page.locator('.mobileTabBar')
  await expect(bar).toBeVisible()
  await expect(bar.locator('.mobileTabButton')).toHaveCount(4)

  const browse = bar.getByRole('button', { name: 'Browse' })
  const editor = bar.getByRole('button', { name: 'Editor' })
  const chat = bar.getByRole('button', { name: 'Chat' })
  const pending = bar.getByRole('button', { name: 'Pending' })

  // Baseline: all tabs should be reachable.
  await expectHorizontallyInViewport(page, browse)
  await expectHorizontallyInViewport(page, editor)
  await expectHorizontallyInViewport(page, chat)
  await expectHorizontallyInViewport(page, pending)

  // Regression harness: simulate a scenario where the layout might be horizontally “panned”
  // (e.g. from visualViewport.offsetLeft / visualViewport.width usage).
  await page.evaluate(() => {
    document.documentElement.style.setProperty('--ochre-vv-left', '140px')
    document.documentElement.style.setProperty('--ochre-vw', '280px')
  })

  await editor.click()
  await expect(page.locator('.mobileSubtitle')).not.toHaveText('Chat')

  // The important part: the right-side tabs (Chat/Pending) must still be on-screen.
  await expect(bar).toBeVisible()
  await expect(bar.locator('.mobileTabButton')).toHaveCount(4)

  await expectHorizontallyInViewport(page, browse)
  await expectHorizontallyInViewport(page, editor)
  await expectHorizontallyInViewport(page, chat)
  await expectHorizontallyInViewport(page, pending)
})

