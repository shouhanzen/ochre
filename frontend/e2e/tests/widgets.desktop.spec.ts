import { expect, test } from '@playwright/test'

test('WidgetFile expands and loads content', async ({ page }) => {
  let sessionRequestMatched = false

  // 1. Mock the session retrieval
  await page.route('**/api/sessions/*', async (route) => {
    sessionRequestMatched = true
    if (route.request().method() === 'GET') {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          id: 'mock-session-id',
          messages: [
            {
              id: 'msg1',
              role: 'assistant',
              content: 'Check this file:\n```widget:file\n{"path":"/mock/file.txt"}\n```',
              created_at: new Date().toISOString()
            }
          ]
        })
      })
      return
    }
    await route.continue()
  })

  // 2. Mock the file read API
  await page.route('**/api/fs/read?path=%2Fmock%2Ffile.txt', async (route) => {
    await new Promise(r => setTimeout(r, 500))
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        content: 'Mock File Content'
      })
    })
  })

  // 3. Load the app with pre-seeded session ID
  await page.goto('/')
  await page.evaluate(() => {
    localStorage.setItem('ochre.selectedSessionId', 'mock-session-id')
  })
  await page.reload()

  // Verify we hit the mock
  await expect.poll(() => sessionRequestMatched).toBe(true)

  // 4. Locate the widget
  // Wait for the message bubble first
  await expect(page.locator('.chatLine.assistant')).toBeVisible()
  
  const widget = page.locator('.widget-file')
  await expect(widget).toBeVisible()
  await expect(widget).toContainText('/mock/file.txt')

  // 5. Expand
  await widget.click()

  // 6. Expect content to load
  // This expectation should fail if the bug exists (it will be stuck on Loading...)
  // We expect "Mock File Content" to eventually appear.
  await expect(page.locator('.widget-file pre code')).toContainText('Mock File Content', { timeout: 5000 })
})
