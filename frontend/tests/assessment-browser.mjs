/** Exercise the local production build with a real Chromium browser, including its offline export. */
import assert from "node:assert/strict";
import { existsSync, mkdtempSync, unlinkSync, rmdirSync } from "node:fs";
import path from "node:path";
import { pathToFileURL } from "node:url";
import { chromium } from "playwright-core";
const base = process.env.BETTER_URL || "http://127.0.0.1:8765";
const executable =
  process.env.CHROME_PATH ||
  [
    "C:/Program Files/Google/Chrome/Application/chrome.exe",
    "C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe",
  ].find(existsSync);
if (!executable)
  throw Error("Set CHROME_PATH to an installed Chromium browser.");
const browser = await chromium.launch({
  executablePath: executable,
  headless: true,
  args: ["--disable-gpu", "--no-first-run"],
});
const context = await browser.newContext({
  viewport: { width: 1366, height: 940 },
  acceptDownloads: true,
});
const page = await context.newPage();
const testFolder = mkdtempSync(path.resolve("../temp/assessment-export-"));
const savedReport = path.join(testFolder, "walks.html");
const errors = [];
page.on("pageerror", (e) => errors.push(e.message));
const readPlot = () =>
  page.locator(".js-plotly-plot").evaluate((el) => el.data.map((t) => t.name));
async function waitTrace(name) {
  await page.waitForFunction(
    (n) =>
      document
        .querySelector(".js-plotly-plot")
        ?.data?.some((t) => t.name === n),
    name,
  );
}
try {
  await page.goto(base);
  await waitTrace("Right walk");
  await page.getByText("How to read this graph.", { exact:true }).waitFor();
  assert.match(await page.locator(".graph-guide").innerText(), /halfway.*the hip bending/s);
  await page.getByText("Read the first mark.", { exact:true }).waitFor();
  assert.equal(await page.locator(".js-plotly-plot .xtitle").textContent(), "Gait cycle (%)");
  assert.equal(await page.locator(".js-plotly-plot .ytitle").textContent(), "Angle (°)");
  assert((await readPlot()).includes("Left walk"));
  const directory = await (
    await context.request.get(base + "/api/directory")
  ).json();
  assert.equal(directory.people.length, 104);
  assert.equal(await page.locator(".patient").count(), 104);
  const person = directory.people[1];
  await page
    .getByRole("textbox", { name: "Search patients by name" })
    .fill(person.name);
  await page
    .locator(".patient")
    .filter({ hasText: person.name })
    .first()
    .click();
  assert.equal(await page.locator("h1").innerText(), person.name);
  await page.getByLabel("Select motion").selectOption("pelvic_tilt");
  await waitTrace("Left manual marks");
  assert.match(await page.locator(".graph-guide").innerText(), /pelvis tilting forward/);
  const saved = await (await context.request.get(base + "/api/participants/" + person.key)).json();
  if (saved.comparison.pelvic_tilt) {
    await page.getByRole("heading", { name: "How the two walks compare" }).waitFor();
    await page.getByText("The size of the gap between the two curves", { exact: false }).waitFor();
  } else {
    await page.getByText("Same-day comparison statistics are unavailable.", { exact: false }).waitFor();
  }
  await page
    .getByText("This motion has no dedicated pattern check.", { exact: false })
    .waitFor();
  await page.getByText("Compare phase angles", {exact:true}).click();
  assert.equal(await page.locator(".phase-review tbody tr").count(),8);
  assert.equal(await page.locator(".phase-review tbody tr").first().locator("td").count(),3);
  await page.getByLabel("Healthy-group spread").selectOption("right");
  await waitTrace("Right healthy group · 5th–95th percentile");
  await page.getByRole("button", { name: "Left", exact: true }).click();
  await page.waitForFunction(() => {
    const p = document.querySelector(".js-plotly-plot");
    return p?.data && !p.data.some((t) => t.name === "Right walk");
  });
  assert.equal(
    await page.getByLabel("Healthy-group spread").inputValue(),
    "off",
  );
  await page.getByRole("button", { name: "Both", exact: true }).click();
  await page.getByLabel("Select motion").selectOption("ankle_dorsiflexion");
  await waitTrace("Reference curve");
  await page.getByRole("button", { name: "Highlight 0–60% on graph" }).click();
  await page.waitForFunction(() =>
    document
      .querySelector(".js-plotly-plot")
      ?.layout.shapes.some((s) => s.type === "rect" && s.x1 === 60),
  );
  await page.getByLabel("Manual phase marks", { exact: true }).uncheck();
  assert.equal(await page.getByText("Read the first mark.", { exact:true }).count(), 0);
  await page.waitForFunction(() => {
    const p = document.querySelector(".js-plotly-plot");
    return p?.data && !p.data.some((t) => t.name.includes("manual marks"));
  });
  const [pdf] = await Promise.all([
    page.waitForEvent("download"),
    page.getByRole("link", { name: "Download PDF" }).click(),
  ]);
  assert.equal(pdf.suggestedFilename(), person.name + ".pdf");
  assert.equal(await pdf.failure(), null);
  const [download] = await Promise.all([
    page.waitForEvent("download"),
    page.getByRole("link", { name: "Interactive HTML" }).click(),
  ]);
  assert(download.suggestedFilename().endsWith(".html"));
  await download.saveAs(savedReport);
  const disk = await context.newPage();
  await disk.route(/^https?:/, (r) => r.abort());
  await disk.goto(pathToFileURL(savedReport).href);
  await disk.waitForFunction(
    () => document.querySelectorAll(".js-plotly-plot").length === 10,
  );
  assert.equal(
    await disk
      .locator(".js-plotly-plot")
      .evaluateAll(
        (plots) =>
          plots.filter((el) =>
            el.data.some((t) => t.name.includes("manual marks")),
          ).length,
      ),
    0,
  );
  assert.equal(await disk.locator("tbody tr").count(),80);
  await disk.getByText(/Read from left to right through one walking cycle/).waitFor();
  await disk.close();
  await page.getByRole("button", { name: "Evidence & assistant" }).click();
  await page
    .getByRole("textbox", { name: "Your question" })
    .fill("What does offset mean?");
  await page.getByRole("button", { name: "Explain this walk" }).click();
  await page.locator(".response h3").waitFor({ timeout: 420000 });
  assert((await page.locator(".response .sources a").count()) > 0);
  await page.getByText(/Offset tells you whether/).waitFor();
  await page.getByRole("textbox", {name:"Your question"}).fill("What was my ankle angle at 45%?");
  await page.getByRole("button", {name:"Explain this walk"}).click();
  await page.getByText(/At 45% of this cycle, the recorded angle was/).waitFor();
  console.log(
    "Assistant mode:",
    await page.locator(".response h3").innerText(),
  );
  await page.getByRole("button", { name: "Right", exact: true }).click();
  assert.equal(await page.locator(".response").count(), 0);
  await page.setViewportSize({ width: 375, height: 812 });
  await page.getByRole("button", { name: "Motion analysis" }).click();
  await waitTrace("Right walk");
  assert(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= window.innerWidth + 1,
    ),
  );
  await page.getByRole("button", { name: "Choose patient" }).click();
  await page.getByRole("textbox", { name: "Search patients by name" }).fill("");
  await page.locator(".patient").first().click();
  await page.getByRole("button", { name: "Choose patient" }).waitFor();
  await page.setViewportSize({ width:320, height:812 });
  await page.getByLabel("Select motion").selectOption("hip_rotation");
  await page.getByLabel("Healthy-group spread").selectOption("right");
  await waitTrace("Right healthy group · 5th–95th percentile");
  assert(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1));
  const plot = page.locator(".js-plotly-plot");
  assert(await plot.locator(".legendtext").first().evaluate(el =>
    el.getBoundingClientRect().top > document.querySelector(".js-plotly-plot .xtitle").getBoundingClientRect().bottom));
  assert(await plot.locator(".textpoint:visible").count() === 0);
  assert(await plot.locator(".point:visible").count() >= 16);
  assert.deepEqual(errors, []);
  console.log(
    "PASS · names/search, desktop and mobile, bilateral and single curves, separate references and phase marks, check windows, standalone offline ten-chart export, assistant binding, zero browser errors.",
  );
} finally {
  await browser.close();
  if (existsSync(savedReport)) unlinkSync(savedReport);
  rmdirSync(testFolder);
}
