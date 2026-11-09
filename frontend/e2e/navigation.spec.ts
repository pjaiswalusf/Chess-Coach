import { expect, test } from '@playwright/test';

const routes = [
	{ label: 'Dashboard', path: '/' },
	{ label: 'Sync', path: '/sync' },
	{ label: 'Games', path: '/games' },
	{ label: 'Coach', path: '/coach' },
	{ label: 'Training', path: '/training' },
	{ label: 'System', path: '/system' }
];

test.beforeEach(async ({ page }) => {
	await page.route('**/health', (route) => route.fulfill({ json: { status: 'ok' } }));
	await page.route('**/api/v1/games', (route) =>
		route.fulfill({ json: { items: [], total: 0, limit: 20, offset: 0 } })
	);
	await page.route('**/api/v1/system', (route) =>
		route.fulfill({
			json: {
				status: 'healthy',
				components: {
					database: { status: 'available' },
					stockfish: { status: 'available' },
					ollama: { status: 'available' }
				},
				statistics: { games_stored: 0, games_analyzed: 0, pending_games: 0 }
			}
		})
	);
});

test('navigates all six pages with current links, direct entry, and browser history', async ({
	page
}) => {
	await page.goto('/');
	await expect(page.getByRole('heading', { name: 'Dashboard', exact: true })).toBeVisible();
	const nav = page.getByRole('navigation', { name: 'Main navigation' });
	for (const { label, path } of routes) {
		const link = nav.getByRole('link', { name: label, exact: true });
		await link.click();
		await expect(page).toHaveURL(path);
		await expect(page.getByRole('heading', { name: label, exact: true })).toBeVisible();
		await expect(link).toHaveAttribute('aria-current', 'page');
		await expect(nav.locator('[aria-current]')).toHaveCount(1);
	}
	await page.mouse.move(0, 0);
	const inactiveBackground = await nav
		.getByRole('link', { name: 'Dashboard' })
		.evaluate((link) => getComputedStyle(link).backgroundColor);
	await expect(nav.getByRole('link', { name: 'System' })).not.toHaveCSS(
		'background-color',
		inactiveBackground
	);
	await page.goBack();
	await expect(page).toHaveURL('/training');
	await expect(nav.getByRole('link', { name: 'Training' })).toHaveAttribute('aria-current', 'page');
	await page.goForward();
	await expect(page.getByRole('heading', { name: 'System' })).toBeVisible();

	for (const { label, path } of routes) {
		await page.goto(path);
		await expect(page.getByRole('heading', { name: label, exact: true })).toBeVisible();
	}
});

test('supports keyboard navigation and fits a narrow viewport', async ({ page }) => {
	await page.setViewportSize({ width: 375, height: 720 });
	await page.goto('/');
	const skip = page.getByRole('link', { name: 'Skip to content' });
	await page.keyboard.press('Tab');
	await expect(skip).toBeFocused();
	await expect(skip).toBeInViewport();
	await page.keyboard.press('Enter');
	await expect(page.getByRole('main')).toBeFocused();

	await page.goto('/');
	await page.keyboard.press('Tab');
	await page.keyboard.press('Tab');
	await page.keyboard.press('Tab');
	const sync = page.getByRole('navigation').getByRole('link', { name: 'Sync' });
	await expect(sync).toBeFocused();
	await page.keyboard.press('Enter');
	await expect(page.getByRole('heading', { name: 'Sync', exact: true })).toBeVisible();
	await expect
		.poll(() => page.evaluate(() => document.documentElement.scrollWidth))
		.toBeLessThanOrEqual(375);
});

test('shows a safe 404 with a working return link', async ({ page }) => {
	const response = await page.goto('/route-does-not-exist');
	expect(response?.status()).toBe(404);
	await expect(page.getByRole('heading', { name: 'Page not found' })).toBeVisible();
	await page.getByRole('link', { name: 'Return to Dashboard' }).click();
	await expect(page).toHaveURL('/');
	await expect(page.getByRole('heading', { name: 'Dashboard' })).toBeVisible();
});
