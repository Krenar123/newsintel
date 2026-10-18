import { expect, test, type Page } from "@playwright/test";

const API_URL = process.env.E2E_API_URL || "http://127.0.0.1:8000";

async function signIn(page: Page, email: string, password: string, workspace: string) {
  await page.goto("/");
  await page.getByRole("button", { name: new RegExp(workspace, "i") }).click();
  await page.getByLabel("Email").fill(email);
  await page.getByLabel("Password").fill(password);
  await page.getByRole("button", { name: "Sign In" }).click();
  await expect(page.getByRole("button", { name: "Sign out" })).toBeVisible();
}

test("login explains workspace types without exposing client identities", async ({ page }) => {
  await page.goto("/");

  await expect(page.getByText("Pick the workspace, then sign in with your own account.")).toBeVisible();
  await expect(page.getByText("Христијан Мицкоски")).toHaveCount(0);
  await expect(page.getByRole("button", { name: "Sign In" })).toBeVisible();
});

test("political figure receives a personalized, responsive workspace", async ({ page }) => {
  await signIn(page, "mickoski@newsintel.local", "Demo123!", "Defense Desk");

  await expect(page.getByRole("heading", { name: "What needs your attention" })).toBeVisible({ timeout: 90_000 });
  await expect(page.getByText("Who is criticizing you?", { exact: true })).toBeVisible();
  await expect(page.getByText("Recent coverage", { exact: true })).toBeVisible();
  await expect(page.getByText("Pilot readiness", { exact: true })).toHaveCount(0);
  await expect(page.getByText("These are recent mentions. They are not automatically classified as attacks.")).toBeVisible();
  await expect(page.getByLabel("Search people, topics, and articles")).toHaveCount(0);

  await page.getByRole("button", { name: "7 days", exact: true }).click();
  await expect(page.getByRole("button", { name: "7 days", exact: true })).toHaveAttribute("aria-pressed", "true");
  await expect(page.getByText("Last week", { exact: true })).toBeVisible();
  await expect(page.getByRole("heading", { name: "What needs your attention" })).toBeVisible({ timeout: 90_000 });

  await page.getByRole("button", { name: /^Attacks/ }).click();
  await expect(page.getByRole("heading", { name: "Why you are being attacked" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "What needs your attention" })).toHaveCount(0);

  await page.getByRole("button", { name: /^Portals/ }).click();
  await expect(page.getByRole("heading", { name: "Attack coverage by portal" })).toBeVisible();
  await expect(page.getByText("Ordinary mentions are excluded.", { exact: false })).toBeVisible();

  await page.getByRole("button", { name: /^Cases/ }).click();
  await expect(page.getByRole("heading", { name: "Saved attacks and response history" })).toBeVisible();

  const horizontalOverflow = await page.evaluate(
    () => document.documentElement.scrollWidth > window.innerWidth,
  );
  expect(horizontalOverflow).toBe(false);
});

const clientWorkspaces = [
  {
    email: "party@newsintel.local",
    workspace: "Party War Room",
    heading: "Prepare the next public move",
    metric: "Press scope",
  },
  {
    email: "pr@newsintel.local",
    workspace: "PR Agency Client Desk",
    heading: "Manage client reputation from one place",
    metric: "Client scope",
  },
  {
    email: "journalist@newsintel.local",
    workspace: "Journalist Research",
    heading: "Find the story, source trail, and context",
    metric: "Research scope",
  },
  {
    email: "media@newsintel.local",
    workspace: "Media Analyst",
    heading: "Understand what is moving in the country",
    metric: "Narratives",
  },
  {
    email: "diaspora@newsintel.local",
    workspace: "Diaspora Daily Digest",
    heading: "Simple Macedonia briefing",
    metric: "My interests",
  },
];

for (const role of clientWorkspaces) {
  test(`${role.workspace} receives its own decision-focused workspace`, async ({ page }) => {
    await signIn(page, role.email, "Demo123!", role.workspace);
    await expect(page.getByRole("heading", { name: role.heading })).toBeVisible({ timeout: 90_000 });
    await expect(page.getByText(role.metric, { exact: true }).first()).toBeVisible();
    await expect(page.getByText("Ask NewsIntel", { exact: true }).first()).toBeVisible();
  });
}

test("admin sees audited legal review controls", async ({ page }) => {
  await signIn(page, "admin@newsintel.local", "ChangeMe123!", "Platform Control Room");
  await expect(page.getByRole("heading", { name: "Overview" })).toBeVisible();
  await page.getByRole("button", { name: "Admin", exact: true }).click();

  await expect(page.getByRole("heading", { name: "Attack Review Queue", exact: true })).toBeVisible({ timeout: 90_000 });
  await expect(page.getByRole("heading", { name: "Legal Readiness", exact: true })).toBeVisible({ timeout: 90_000 });
  await page.getByRole("button", { name: "Review decision" }).first().click();
  await expect(page.getByText("Audited Legal Review", { exact: true })).toBeVisible();
  await expect(page.getByText("Lawyer verification requires a matching counsel assignment", { exact: false })).toBeVisible();
});

test("admin can save and reopen a filtered bilingual search", async ({ page }) => {
  await signIn(page, "admin@newsintel.local", "ChangeMe123!", "Platform Control Room");
  await page.getByRole("button", { name: "Articles", exact: true }).click();

  await page.getByLabel("Search people, topics, and articles").fill("makedonija");
  await page.getByLabel("Saved search name").fill("Macedonia coverage");
  await page.getByRole("button", { name: "Save current search" }).click();
  await expect(page.getByText("Search saved privately.")).toBeVisible({ timeout: 30_000 });

  await page.getByRole("button", { name: "Macedonia coverage makedonija", exact: true }).last().click();
  await expect(page.getByLabel("Search people, topics, and articles")).toHaveValue("makedonija");
  await page.getByRole("button", { name: "Delete Macedonia coverage" }).last().click();
  await expect(page.getByText("Saved search removed.")).toBeVisible();
});

test("non-admin accounts cannot access the legal review queue", async ({ request }) => {
  const login = await request.post(`${API_URL}/api/v1/auth/login`, {
    data: { email: "analyst@newsintel.local", password: "Demo123!" },
  });
  expect(login.ok()).toBe(true);
  const token = (await login.json()).access_token;

  const queue = await request.get(`${API_URL}/api/v1/admin/legal/review-queue?country_code=mk`, {
    headers: { Authorization: `Bearer ${token}` },
  });
  expect(queue.status()).toBe(403);
});

test("client accounts cannot open another client's workspace data", async ({ request }) => {
  const login = await request.post(`${API_URL}/api/v1/auth/login`, {
    data: { email: "party@newsintel.local", password: "Demo123!" },
  });
  expect(login.ok()).toBe(true);
  const session = await login.json();
  const ownClientId = session.user.client_id as number;
  const otherClientId = ownClientId === 1 ? 2 : 1;

  const ownDashboard = await request.get(
    `${API_URL}/api/v1/clients/${ownClientId}/dashboard`,
    { headers: { Authorization: `Bearer ${session.access_token}` } },
  );
  expect(ownDashboard.ok()).toBe(true);

  const otherDashboard = await request.get(
    `${API_URL}/api/v1/clients/${otherClientId}/dashboard`,
    { headers: { Authorization: `Bearer ${session.access_token}` } },
  );
  expect(otherDashboard.status()).toBe(403);
});
