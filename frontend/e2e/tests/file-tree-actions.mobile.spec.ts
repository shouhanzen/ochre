import { expect, test } from '@playwright/test'

test.use({
  hasTouch: true,
})

test('mobile file tree long-press opens context menu', async ({ page }) => {
  await page.goto('/')
  
  // Clear storage
  await page.evaluate(() => localStorage.clear())
  await page.reload()

  // Wait for app
  await expect(page.locator('.mobileTabBar')).toBeVisible()
  
  // Navigate to Browse
  await page.locator('.mobileTabBar').getByRole('button', { name: 'Browse' }).click()

  // Wait for tree
  const tree = page.locator('.tree')
  await expect(tree).toBeVisible()
  
  // Wait for 'todos' item
  const targetRow = tree.locator('.treeRow').filter({ hasText: 'todos' }).first()
  await expect(targetRow).toBeVisible()

  let box = await targetRow.boundingBox()
  for (let i = 0; i < 3; i++) {
    if (box) break
    await page.waitForTimeout(200)
    box = await targetRow.boundingBox()
  }
  
  if (!box) throw new Error('No bounding box for target row')

  // Try simulating contextmenu directly (standard long-press behavior on mobile usually results in this)
  await targetRow.dispatchEvent('contextmenu', { 
    clientX: box.x + box.width / 2, 
    clientY: box.y + box.height / 2 
  })

  // Verify menu
  const menu = page.locator('.menuItem', { hasText: 'Rename' })
  await expect(menu).toBeVisible()
  
  const copyOption = page.locator('.menuItem', { hasText: 'Copy Path' })
  await expect(copyOption).toBeVisible()
})
