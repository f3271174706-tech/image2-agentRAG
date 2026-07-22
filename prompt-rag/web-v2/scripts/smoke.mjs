import { chromium } from "playwright-core";

const executablePath =
  process.env.EDGE_PATH || "C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe";
const baseUrl = process.env.PROMPT_STUDIO_URL || "http://127.0.0.1:8010/v2/";

const browser = await chromium.launch({ executablePath, headless: true });
const page = await browser.newPage({ viewport: { width: 1600, height: 1100 } });

try {
  await page.goto(baseUrl, { waitUntil: "networkidle" });
  await page.locator("textarea").fill("现代电影感游戏画面");
  await page.getByRole("button", { name: "开始创作" }).click();
  await page.locator("#requirement-review").waitFor({ timeout: 120_000 });
  const structuredSubject = await page.locator('.review-form-grid label:has-text("主体") input').inputValue();
  if (!structuredSubject.trim()) throw new Error("Requirement understanding did not produce a subject");
  await page.locator('.review-form-grid label:has-text("环境") input').fill("雨夜霓虹城市");
  await page.screenshot({ path: "../logs/prompt-studio-v2-requirement-review.png", fullPage: true });
  await page.getByRole("button", { name: "确认并检索模板" }).click();
  await page.locator(".main-candidate").waitFor({ timeout: 60_000 });

  if (await page.locator('[data-testid="expanded-original"]').count()) {
    throw new Error("Original prompt is visible before the expand action");
  }
  const originalButton = page.getByRole("button", { name: "展开完整原文" });
  await originalButton.click();
  await page.locator('[data-testid="expanded-original"]').waitFor();
  const originalLength = (await page.locator(".original-prompt p").textContent())?.length ?? 0;
  if (originalLength < 100) throw new Error("Original prompt did not expand completely");

  const firstTitle = await page.locator(".main-candidate h3").textContent();
  await page.locator(".candidate-tabs button").first().click();
  const nextTitle = await page.locator(".main-candidate h3").textContent();
  if (!nextTitle || nextTitle === firstTitle) throw new Error("Candidate switching did not update the main card");
  if (await page.locator('[data-testid="expanded-original"]').count()) {
    throw new Error("Expanded prompt leaked into the newly selected candidate");
  }

  await page.getByRole("button", { name: "采用并智能编排" }).click();
  await page.locator("#final-prompt").waitFor({ timeout: 180_000 });
  const finalPrompt = (await page.locator(".final-prompt-body").textContent()) ?? "";
  const chineseCharacters = (finalPrompt.match(/[\u4e00-\u9fff]/g) ?? []).length;
  if (finalPrompt.length < 100 || chineseCharacters < 20) {
    throw new Error("The default final prompt was not translated to Chinese");
  }
  if (!(await page.getByRole("button", { name: "查看编排原文" }).isVisible())) {
    throw new Error("The source prompt toggle is missing");
  }
  await page.screenshot({ path: "../logs/prompt-studio-v2-results.png", fullPage: true });
  await page.locator(".candidate-tabs button").first().click();
  if (await page.locator("#final-prompt").count()) {
    throw new Error("A stale final prompt remained after changing candidates");
  }
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto(baseUrl, { waitUntil: "networkidle" });
  const mobileLayout = await page.evaluate(() => ({
    viewport: window.innerWidth,
    content: document.documentElement.scrollWidth,
    sidebarVisible: getComputedStyle(document.querySelector(".sidebar")).transform === "none",
  }));
  if (mobileLayout.content > mobileLayout.viewport) throw new Error("Mobile layout overflows horizontally");
  await page.screenshot({ path: "../logs/prompt-studio-v2-mobile.png", fullPage: true });
  console.log(JSON.stringify({ ok: true, structuredSubject, originalLength, finalPromptLength: finalPrompt.length, chineseCharacters, firstTitle, nextTitle, mobileLayout }));
} finally {
  await browser.close();
}
