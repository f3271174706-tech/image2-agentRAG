import { chromium } from "playwright-core";

const executablePath =
  process.env.EDGE_PATH || "C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe";
const baseUrl = process.env.PROMPT_MANAGE_URL || "http://127.0.0.1:8012/manage";
const password = process.env.PROMPT_MANAGE_PASSWORD || "local-manage-smoke-password";
const smokeId = `manual-ui-smoke-${Date.now()}`;

const browser = await chromium.launch({ executablePath, headless: true });
const page = await browser.newPage({ viewport: { width: 1500, height: 1000 } });

try {
  await page.goto(baseUrl, { waitUntil: "networkidle" });
  await page.getByLabel("管理员密码").fill(password);
  await page.getByRole("button", { name: "进入管理中心" }).click();
  await page.getByRole("heading", { name: "让知识库保持清晰、可控、可检索" }).waitFor();
  await page.waitForFunction(() => {
    const value = document.querySelector(".manage-stat strong")?.textContent || "0";
    return Number(value.replaceAll(",", "")) > 0;
  });

  const totalBefore = await page.locator(".manage-stat strong").first().textContent();
  await page.getByRole("button", { name: "新增提示词" }).click();
  await page.getByLabel("完整提示词").fill("A luminous aurora fox walking across a quiet snowy game landscape, cinematic lighting.");
  await page.locator(".simple-fields select").selectOption("game-asset");
  await page.getByLabel("标题（可选）").fill(smokeId);
  await page.screenshot({ path: "../logs/prompt-manage-simple-modal.png", fullPage: true });
  await page.getByRole("button", { name: "保存到知识库" }).click();
  await page.locator(".manage-notice").waitFor();

  await page.locator(".manage-search input").fill(smokeId);
  await page.locator(".manage-filters > button").click();
  const row = page.locator("tbody tr", { hasText: smokeId });
  await row.waitFor();
  await row.getByTitle("停用").click();
  await page.locator(".manage-notice").waitFor();
  await page.screenshot({ path: "../logs/prompt-manage-desktop.png", fullPage: true });

  await page.setViewportSize({ width: 390, height: 844 });
  await page.reload({ waitUntil: "networkidle" });
  const mobileLayout = await page.evaluate(() => ({
    viewport: window.innerWidth,
    content: document.documentElement.scrollWidth,
  }));
  if (mobileLayout.content > mobileLayout.viewport) {
    throw new Error(`Management center overflows on mobile: ${JSON.stringify(mobileLayout)}`);
  }
  await page.screenshot({ path: "../logs/prompt-manage-mobile.png", fullPage: true });
  console.log(JSON.stringify({ ok: true, totalBefore, mobileLayout }));
} finally {
  await browser.close();
}
