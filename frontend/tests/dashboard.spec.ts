import { test, expect } from '@playwright/test';

test.describe('Dashboard E2E', () => {
    test.beforeEach(async ({ page }) => {
        // Mock the tokens endpoint so we can login
        await page.route('**/api/v1/auth/token', async (route) => {
            await route.fulfill({
                status: 200,
                contentType: 'application/json',
                json: { access_token: 'fake-token', role: 'admin', token_type: 'bearer' },
            });
        });

        // Mock API responses for dashboard initialization
        await page.route('**/api/v1/stats', async (route) => {
            await route.fulfill({
                status: 200,
                contentType: 'application/json',
                json: {
                    NORMAL: 100,
                    RESTRICTED_WITHDRAWAL: 5,
                    UNDER_SURVEILLANCE: 2,
                    BANNED: 1,
                    total_accounts: 108,
                    total_transitions: 14,
                    blocked_withdrawals: 3,
                    l1_flags: 8,
                    l2_analyses: 4,
                    total_events: 500
                },
            });
        });

        await page.route('**/api/v1/events/recent*', async (route) => {
            await route.fulfill({
                status: 200,
                contentType: 'application/json',
                json: [],
            });
        });

        await page.route('**/api/v1/analyses*', async (route) => {
            await route.fulfill({
                status: 200,
                contentType: 'application/json',
                json: [],
            });
        });

        await page.route('**/api/v1/graph', async (route) => {
            await route.fulfill({
                status: 200,
                contentType: 'application/json',
                json: { nodes: [], links: [] },
            });
        });

        await page.route('**/api/v1/users', async (route) => {
            await route.fulfill({
                status: 200,
                contentType: 'application/json',
                json: [],
            });
        });
    });

    test('should login and display main dashboard elements', async ({ page }) => {
        // Go to index page
        await page.goto('/');

        // Verify Login page is displayed
        await expect(page.locator('text=Susanoh Admin')).toBeVisible();

        // Fill in credentials
        await page.fill('input[type="text"]', 'admin');
        await page.fill('input[type="password"]', 'password123');

        // Click Sign In
        await page.click('button[type="submit"]');

        // Verify we are logged in and dashboard is rendered
        // The header text "Susanoh" should be visible (there's also an h1 "Susanoh" without Admin)
        await expect(page.locator('h1:has-text("Susanoh")').first()).toBeVisible();

        // Verify stats from the mock
        await expect(page.locator('text=500 events processed')).toBeVisible(); // total events

        // Verify components are rendered
        await expect(page.locator('text=AI Audit Report')).toBeVisible();
        await expect(page.locator('text=Incident Timeline')).toBeVisible();
        await expect(page.locator('text=Real-Time Events')).toBeVisible();
    });
});
