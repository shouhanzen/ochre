import { expect, test } from '@playwright/test'

test('file tree copy subtree action (desktop)', async ({ page }) => {
  await page.goto('/')
  
  // Clear storage
  await page.evaluate(() => localStorage.clear())
  await page.reload()

  // Wait for sidebar tree
  try {
    const tree = page.locator('.sideBar .tree')
    await expect(tree).toBeVisible({ timeout: 10000 })
  } catch (e) {
    console.log('Sidebar tree not found. Content:', await page.content())
    throw e
  }
  const tree = page.locator('.sideBar .tree')
  
  // Wait for 'todos' item
  const targetRow = tree.locator('.treeRow').filter({ hasText: 'todos' }).first()
  await expect(targetRow).toBeVisible()

  // Mock clipboard permission if possible, but the error suggests it might be a context issue
  // We'll try to rely on the browser's native behavior first to reproduce the error
  // If we can't reproduce it directly, we might need to mock the failure case

  // Right click
  await targetRow.click({ button: 'right' })
  
  // Check for Copy Subtree button
  const copySubtreeBtn = page.locator('.menuItem', { hasText: 'Copy Subtree' })
  await expect(copySubtreeBtn).toBeVisible()
  
  // Click it
  await copySubtreeBtn.click()
  
  // We expect this to NOT throw an alert in a happy path, but if the user says it failed...
  // The user says "The request is not allowed..." which is typical for clipboard.writeText
  // when not triggered by a user activation or if the document is not focused.
  
  // However, `click` is a user activation. The issue might be the `await fsTree(...)` call
  // which makes the clipboard write async and "detached" from the click event loop in some browsers.
})
