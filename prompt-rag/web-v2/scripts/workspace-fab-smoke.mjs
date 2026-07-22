import { chromium } from "playwright-core";

const executablePath =
  process.env.EDGE_PATH || "C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe";
const baseUrl = process.env.PROMPT_WORKSPACE_URL || "http://127.0.0.1:8012/v2/";

const browser = await chromium.launch({ executablePath, headless: true });
const page = await browser.newPage({ viewport: { width: 1500, height: 900 } });

try {
  await page.goto(baseUrl, { waitUntil: "networkidle" });
  const entry = page.getByRole("link", { name: "进入知识库管理中心" });
  await entry.waitFor();
  const href = await entry.getAttribute("href");
  if (href !== "/manage") throw new Error(`Unexpected management href: ${href}`);

  await page.setViewportSize({ width: 390, height: 844 });
  await page.reload({ waitUntil: "networkidle" });
  const mobile = await entry.boundingBox();
  if (!mobile || mobile.x + mobile.width > 390 || mobile.y + mobile.height > 844) {
    throw new Error(`Management entry is outside the mobile viewport: ${JSON.stringify(mobile)}`);
  }
  await page.screenshot({ path: "../logs/prompt-workspace-manage-entry.png", fullPage: true });

  await entry.click();
  await page.waitForURL(/\/manage/);
  console.log(JSON.stringify({ ok: true, href, mobile }));
} finally {
  await browser.close();
}
