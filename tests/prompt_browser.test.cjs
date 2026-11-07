// Requires playwright and Python with aiohttp. Uses only a temporary synthetic DB.
const { test, before, after } = require("node:test");
const assert = require("node:assert/strict");
const { spawn } = require("node:child_process");
const { once } = require("node:events");
const { chromium } = require("playwright");
const net = require("node:net");

let server, browser, base;
before(async () => {
    const socket = net.createServer(); socket.listen(0, "127.0.0.1"); await once(socket, "listening");
    const port = socket.address().port; await new Promise(resolve => socket.close(resolve));
    base = `http://127.0.0.1:${port}`;
    server = spawn(process.env.PROMPT_TEST_PYTHON || "python3", ["-u", "tests/prompt_test_fixture.py", "--port", String(port)], { stdio: ["ignore", "pipe", "pipe"] });
    let logs = ""; server.stdout.on("data", data => { logs += data; }); server.stderr.on("data", data => { logs += data; });
    for (let attempt = 0; attempt < 100; attempt++) {
        if (server.exitCode !== null) throw new Error(logs);
        try { if ((await fetch(base)).ok) break; } catch {}
        if (attempt === 99) throw new Error(`Fixture did not start: ${logs}`);
        await new Promise(resolve => setTimeout(resolve, 50));
    }
    browser = await chromium.launch({ headless: true });
});
after(async () => { await browser?.close(); if (server && server.exitCode === null) { server.kill("SIGTERM"); await once(server, "exit"); } });

async function pageFor(t, viewport = { width: 1440, height: 1000 }) {
    const page = await browser.newPage({ viewport });
    t.after(() => page.close());
    page.on("dialog", dialog => dialog.accept());
    await page.goto(base);
    await page.waitForFunction(() => Boolean(window.attachTestNode));
    await page.locator("#open").click();
    await page.waitForFunction(() => document.querySelectorAll(".tbp-card").length === 50);
    return page;
}

test("pagination, upper level, tags, category conjunction and literal rendering", async t => {
    const page = await pageFor(t);
    assert.equal(await page.locator(".tbp-card").count(), 50);
    assert.equal(await page.locator(".tbp-card script").count(), 0);
    await page.getByRole("button", { name: "下一页", exact: true }).click();
    await page.waitForFunction(() => document.querySelectorAll(".tbp-card").length === 15);
    await page.getByRole("button", {name:"等级及以下",exact:true}).click();
    await page.locator('.tbp-filters [name="sensitivity_level"]').selectOption("L1");
    await page.waitForFunction(() => document.querySelector(".tbp-result-heading strong").textContent.startsWith("26 "));
    assert.ok((await page.locator(".tbp-level").allTextContents()).every(text => ["L0", "L1"].includes(text)));
    await page.getByRole("button", { name: "重置筛选", exact: true }).click();
    await page.locator('.tbp-tag-option[data-tag="landscape"]').click();
    await page.locator('.tbp-tag-option[data-tag="night"]').click();
    await page.waitForFunction(() => document.querySelector(".tbp-result-heading strong").textContent.startsWith("32 "));
    assert.equal(await page.locator(".tbp-selected-tag").count(), 2);
    await page.locator('.tbp-filters [name="nsfw"]').selectOption("否");
    await page.waitForFunction(() => document.querySelector(".tbp-result-heading strong").textContent.startsWith("0 "));
    assert.match(await page.locator(".tbp-results [role=status]").textContent(), /没有匹配/);
});

test("detail saves all fields and uses persisted ID", async t => {
    const page = await pageFor(t);
    await page.locator(".tbp-card").first().click();
    await page.locator(".tbp-editor textarea").waitFor();
    const cardId = Number(await page.locator(".tbp-card").first().getAttribute("data-id"));
    await page.locator('.tbp-editor [name="prompt"]').fill("Edited synthetic prompt <img src=x onerror=alert(1)>");
    await page.locator('.tbp-editor [name="sensitivity_level"]').selectOption("4");
    await page.locator('.tbp-editor [name="gore"]').check();
    await page.locator('.tbp-editor [name="minor"]').check();
    await page.locator('.tbp-editor [name="tags"]').fill("updated, landscape");
    await page.getByRole("button", { name: "保存修改", exact: true }).click();
    await page.getByRole("status").filter({ hasText: /^已保存$/ }).waitFor();
    const saved = await (await page.request.get(`${base}/toolbox/prompts/${cardId}`)).json();
    assert.equal(saved.prompt, "Edited synthetic prompt <img src=x onerror=alert(1)>");
    assert.equal(saved.sensitivity_level, 4); assert.equal(saved.gore, true); assert.equal(saved.minor, true);
    assert.deepEqual(saved.tags, ["landscape", "updated"]);
    await page.getByRole("button", { name: "使用此提示词", exact: true }).click();
    assert.equal(await page.locator("dialog").count(), 0);
    assert.equal(await page.evaluate(() => window.selected), cardId);
});

test("stale record conflict retains unsaved input, reload gets current version", async t => {
    const page = await pageFor(t);
    await page.locator(".tbp-card").nth(1).click();
    await page.locator(".tbp-editor textarea").waitFor();
    const id = Number(await page.locator(".tbp-card").nth(1).getAttribute("data-id"));
    const old = await (await page.request.get(`${base}/toolbox/prompts/${id}`)).json();
    const fields = ["prompt", "language", "media_type", "prompt_type", "nsfw", "content_format", "dynamic", "width", "height", "tags", "sensitivity_level", "extreme", "horror", "gore", "minor", "version"];
    const payload = Object.fromEntries(fields.map(key => [key, old[key]]));
    payload.tags = old.tags.join(","); payload.prompt = "Externally saved synthetic prompt";
    assert.equal((await page.request.patch(`${base}/toolbox/prompts/${id}`, { data: payload })).status(), 200);
    await page.locator(".tbp-editor textarea").fill("My unsaved text");
    await page.getByRole("button", { name: "保存修改", exact: true }).click();
    await page.getByRole("status").filter({ hasText: /记录已被修改/ }).waitFor();
    assert.equal(await page.locator(".tbp-editor textarea").inputValue(), "My unsaved text");
    await page.getByRole("button", { name: "重新加载详情", exact: true }).click();
    await page.waitForFunction(() => document.querySelector(".tbp-editor textarea").value === "Externally saved synthetic prompt");
});

test("node adapter backfills ID, marks graph changed, closes on node removal and can reopen", async t => {
    const page = await browser.newPage(); t.after(() => page.close());
    await page.goto(base); await page.waitForFunction(() => Boolean(window.attachTestNode));
    await page.evaluate(() => window.attachTestNode());
    const open = page.getByRole("button", { name: "浏览提示词库 · 筛选 / 详情 / 编辑" });
    await open.click();
    await page.locator('.tbp-filters [name="q"]').fill("Synthetic prompt 000");
    await page.waitForFunction(() => document.querySelectorAll(".tbp-card").length === 1);
    await page.locator(".tbp-card").click();
    await page.locator(".tbp-editor textarea").waitFor();
    await page.getByRole("button", { name: "使用此提示词", exact: true }).click();
    assert.deepEqual(await page.evaluate(() => ({ id:window.testNode.widgets[0].value, dirty:window.testNode.dirty, changed:window.testNode.changed, serialize:window.testNode.options.serialize })), { id:1, dirty:true, changed:true, serialize:false });
    await open.click(); await page.locator("dialog:not(.tbp-detail-dialog)[open]").waitFor();
    await page.evaluate(() => window.testNode.onRemoved());
    assert.equal(await page.locator("dialog").count(), 0);
    await open.click(); await page.locator(".tbp-filters").waitFor();
    await page.keyboard.press("Escape");
    assert.equal(await page.locator("dialog").count(), 0);
});

test("two browsers keep separate selections and clean up their detail dialogs", async t => {
    const page = await pageFor(t);
    await page.locator(".tbp-card").nth(2).click();
    await page.locator(".tbp-editor textarea").waitFor();
    const original = await page.locator('.tbp-card[aria-pressed="true"]').getAttribute("data-id");
    await page.getByRole("button", { name: "返回列表", exact: true }).click();
    await page.evaluate(() => document.querySelector("#second").click());
    await page.waitForFunction(() => document.querySelectorAll("dialog:not(.tbp-detail-dialog)").length === 2 && document.querySelectorAll("dialog:not(.tbp-detail-dialog)")[1].querySelectorAll(".tbp-card").length === 50);
    const second = page.locator("dialog:not(.tbp-detail-dialog)").nth(1);
    const secondId = Number(await second.locator(".tbp-card").nth(5).getAttribute("data-id"));
    await second.locator(".tbp-card").nth(5).click();
    const secondDetail = page.locator(".tbp-detail-dialog[open]");
    await secondDetail.locator(".tbp-editor textarea").waitFor();
    await secondDetail.getByRole("button", { name: "使用此提示词", exact: true }).click();
    assert.equal(await page.evaluate(() => window.secondSelected), secondId);
    assert.equal(await page.locator('.tbp-card[aria-pressed="true"]').getAttribute("data-id"), original);
    await page.getByRole("button", { name: "关闭", exact: true }).click();
    assert.equal(await page.locator("dialog").count(), 0);
});

test("list errors are visible and retry recovers; desktop screenshot", async t => {
    const page = await pageFor(t);
    await page.route("**/toolbox/prompts?**", route => route.fulfill({ status:503, contentType:"application/json", body:JSON.stringify({error:"Synthetic database error"}) }));
    await page.getByRole("button", { name: "刷新列表", exact: true }).click();
    await page.getByRole("status").filter({ hasText:"Synthetic database error" }).waitFor();
    await page.unroute("**/toolbox/prompts?**");
    await page.getByRole("button", { name: "刷新列表", exact: true }).click();
    await page.waitForFunction(() => document.querySelectorAll(".tbp-card").length === 50);
    await page.locator(".tbp-card").nth(3).click(); await page.locator(".tbp-editor textarea").waitFor();
    await page.screenshot({ path:"/tmp/toolbox-prompt-reader-desktop.png" });
});

test("narrow viewport stays inside dialog and exposes editor", async t => {
    const page = await pageFor(t, { width:390, height:844 });
    await page.locator(".tbp-card").first().click(); await page.locator(".tbp-editor textarea").waitFor();
    await page.locator(".tbp-editor textarea").scrollIntoViewIfNeeded();
    const textarea = await page.locator(".tbp-editor textarea").boundingBox();
    assert.ok(textarea.y >= 0 && textarea.y < 844);
    assert.ok(await page.evaluate(() => document.querySelector(".tbp-detail-dialog").scrollWidth <= document.querySelector(".tbp-detail-dialog").clientWidth + 1));
    await page.screenshot({ path:"/tmp/toolbox-prompt-reader-mobile.png" });
});

test("a delayed old search cannot replace a newer result; closing cancels in-flight loads", async t => {
    const page = await pageFor(t);
    await page.route("**/toolbox/prompts?**", async route => {
        if (new URL(route.request().url()).searchParams.get("q") === "delayed") {
            await new Promise(resolve => setTimeout(resolve, 500));
            await route.fulfill({ status:200, contentType:"application/json", body:JSON.stringify({items:[],total:0,page:1,page_size:50}) }).catch(() => {});
        } else await route.continue();
    });
    const delayed = page.waitForRequest(request => new URL(request.url()).searchParams.get("q") === "delayed");
    await page.locator('.tbp-filters [name="q"]').fill("delayed");
    await delayed;
    await page.locator('.tbp-filters [name="q"]').fill("Synthetic prompt 001");
    await page.waitForFunction(() => document.querySelector(".tbp-result-heading strong").textContent.startsWith("1 "));
    await page.waitForTimeout(600);
    assert.equal(await page.locator(".tbp-card").count(), 1);
    const closing = page.waitForRequest(request => new URL(request.url()).searchParams.get("q") === "delayed");
    await page.locator('.tbp-filters [name="q"]').fill("delayed"); await closing;
    await page.getByRole("button", { name: "关闭", exact: true }).click();
    await page.waitForTimeout(600);
    assert.equal(await page.locator("dialog").count(), 0);
});


test("details open only on card click, Escape returns to the same page and filters", async t => {
    const page = await pageFor(t);
    assert.equal(await page.locator(".tbp-detail-dialog[open]").count(), 0);
    assert.equal(await page.locator(".tbp-layout aside").count(), 0);
    await page.getByRole("button", { name: "下一页", exact: true }).click();
    await page.waitForFunction(() => document.querySelectorAll(".tbp-card").length === 15);
    const id = await page.locator(".tbp-card").first().getAttribute("data-id");
    await page.locator(".tbp-card").first().click();
    await page.locator(".tbp-detail-dialog[open] .tbp-editor").waitFor();
    await page.keyboard.press("Escape");
    assert.equal(await page.locator(".tbp-detail-dialog[open]").count(), 0);
    assert.equal(await page.locator("dialog:not(.tbp-detail-dialog)[open]").count(), 1);
    assert.match(await page.locator(".tbp-pagination").textContent(), /2 \/ 2/);
    assert.equal(await page.locator(".tbp-card").first().getAttribute("data-id"), id);
    await page.getByRole("button", {name:"等级及以下",exact:true}).click();
    await page.locator('.tbp-filters [name="sensitivity_level"]').selectOption("L1");
    await page.waitForFunction(() => document.querySelector(".tbp-result-heading strong").textContent.startsWith("26 "));
    await page.locator(".tbp-card").first().click(); await page.locator(".tbp-editor textarea").waitFor();
    await page.getByRole("button", { name: "返回列表", exact: true }).click();
    assert.equal(await page.locator('.tbp-filters [name="sensitivity_level"]').inputValue(), "L1");
});


test("specific levels toggle independently, tag search preserves selections and reset clears both", async t => {
    const page = await pageFor(t);
    await page.getByRole("button", {name:"指定级别",exact:true}).click();
    await page.locator('.tbp-level-choice[data-level="0"]').click();
    await page.locator('.tbp-level-choice[data-level="1"]').click();
    await page.locator('.tbp-level-choice[data-level="3"]').click();
    await page.waitForFunction(() => document.querySelectorAll(".tbp-level").length > 0 && [...document.querySelectorAll(".tbp-level")].every(el=>["L1","L3"].includes(el.textContent)));
    assert.equal(await page.locator('.tbp-level-choice[aria-pressed="true"]').count(), 2);
    await page.locator('.tbp-tag-option[data-tag="landscape"]').click();
    await page.getByRole("searchbox", {name:"搜索标签",exact:true}).fill("night");
    assert.equal(await page.locator(".tbp-tag-option").count(), 1);
    assert.equal(await page.getByRole("button", {name:"移除标签 landscape",exact:true}).count(), 1);
    await page.getByRole("button", {name:"重置筛选",exact:true}).click();
    assert.equal(await page.locator(".tbp-selected-tag").count(), 0);
    assert.equal(await page.getByRole("button", {name:"不限",exact:true}).getAttribute("aria-pressed"), "true");
    await page.waitForFunction(() => document.querySelectorAll(".tbp-card").length === 50);
    assert.ok(await page.locator(".tbp-language").count() > 0);
    assert.ok(await page.locator(".tbp-media").count() > 0);
    assert.ok(await page.locator(".tbp-prompt-tag").count() > 0);
});


test("compact dropdown row precedes tags; size selection cascades and custom sizes filter", async t => {
    const page = await pageFor(t);
    const tops = await page.locator(".tbp-common-filters select").evaluateAll(elements => elements.map(el=>Math.round(el.getBoundingClientRect().top)));
    assert.equal(tops.length, 10);
    assert.equal(new Set(tops).size, 1);
    assert.ok(await page.locator(".tbp-tag-picker").evaluate(el => Boolean(el.previousElementSibling?.classList.contains("tbp-size-filter"))));
    await page.locator('.tbp-filters [name="match_size"]').check();
    assert.equal(await page.locator('.tbp-filters [name="size_ratio"]').inputValue(), "4:3");
    assert.equal(await page.locator('.tbp-filters [name="size_resolution"]').inputValue(), "1024x768");
    await page.locator('.tbp-filters [name="size_ratio"]').selectOption("9:16");
    await page.waitForFunction(() => document.querySelector(".tbp-result-heading strong").textContent.startsWith("0 "));
    assert.equal(await page.locator('.tbp-filters [name="size_resolution"]').inputValue(), "720x1280");
    await page.locator('.tbp-filters [name="size_ratio"]').selectOption("custom");
    await page.locator('.tbp-filters [name="width"]').fill("1024");
    await page.locator('.tbp-filters [name="height"]').fill("768");
    await page.waitForFunction(() => document.querySelectorAll(".tbp-card").length === 50);
    await page.locator('.tbp-filters [name="height"]').fill("769");
    await page.waitForFunction(() => document.querySelectorAll(".tbp-card").length === 0);
    await page.locator('.tbp-filters [name="match_size"]').uncheck();
    await page.waitForFunction(() => document.querySelectorAll(".tbp-card").length === 50);
    await page.getByRole("button", {name:"重置筛选",exact:true}).click();
    assert.equal(await page.locator('.tbp-filters [name="size_ratio"]').inputValue(), "4:3");
    assert.equal(await page.locator('.tbp-filters [name="size_resolution"]').inputValue(), "1024x768");
});


test("detail size editor cascades and round-trips preset and custom dimensions", async t => {
    const page = await pageFor(t);
    await page.locator(".tbp-card").first().click();
    const editor = page.locator(".tbp-detail-dialog");
    await editor.locator('[name="edit_ratio"]').waitFor();
    await editor.locator('[name="edit_ratio"]').selectOption("9:16");
    await editor.locator('[name="edit_resolution"]').selectOption("864x1536");
    await editor.getByRole("button", {name:"保存修改",exact:true}).click();
    await editor.getByRole("status").filter({hasText:/^已保存$/}).waitFor();
    assert.equal(await editor.locator('[name="edit_ratio"]').inputValue(), "9:16");
    assert.equal(await editor.locator('[name="edit_resolution"]').inputValue(), "864x1536");
    await editor.locator('[name="edit_ratio"]').selectOption("custom");
    await editor.locator('[name="width"]').fill("900");
    await editor.locator('[name="height"]').fill("1200");
    await editor.getByRole("button", {name:"保存修改",exact:true}).click();
    await editor.getByRole("status").filter({hasText:/^已保存$/}).waitFor();
    assert.equal(await editor.locator('[name="edit_ratio"]').inputValue(), "3:4");
    assert.equal(await editor.locator('[name="edit_resolution"]').inputValue(), "900x1200");
    await editor.locator('[name="edit_ratio"]').selectOption("custom");
    await editor.locator('[name="width"]').fill("1024");
    await editor.locator('[name="height"]').fill("769");
    await editor.getByRole("button", {name:"保存修改",exact:true}).click();
    await editor.getByRole("status").filter({hasText:/^已保存$/}).waitFor();
    assert.equal(await editor.locator('[name="edit_ratio"]').inputValue(), "custom");
    assert.equal(await editor.locator('[name="width"]').inputValue(), "1024");
    assert.equal(await editor.locator('[name="height"]').inputValue(), "769");
});


test("add modal creates then upserts identical prompt and shows the existing-record notice", async t => {
    const page = await pageFor(t);
    await page.getByRole("button", {name:"新增提示词",exact:true}).click();
    const detail = page.locator(".tbp-detail-dialog");
    assert.equal(await detail.getByRole("button", {name:"使用此提示词",exact:true}).isEnabled(), false);
    await detail.locator('[name="prompt"]').fill("Synthetic create and duplicate notice");
    await detail.locator('[name="tags"]').fill("created-test");
    await detail.locator('[name="edit_ratio"]').selectOption("9:16");
    await detail.locator('[name="edit_resolution"]').selectOption("864x1536");
    await detail.getByRole("button", {name:"保存提示词",exact:true}).click();
    await detail.getByRole("status").filter({hasText:/已新增记录/}).waitFor();
    const id = Number((await detail.locator("h3").innerText()).match(/#(\d+)/)[1]);
    const total = (await (await page.request.get(`${base}/toolbox/prompts?page_size=1`)).json()).total;
    await detail.getByRole("button", {name:"返回列表",exact:true}).click();
    await page.getByRole("button", {name:"新增提示词",exact:true}).click();
    await detail.locator('[name="prompt"]').fill("  Synthetic create and duplicate notice  ");
    await detail.locator('[name="tags"]').fill("updated-test");
    await detail.getByRole("button", {name:"保存提示词",exact:true}).click();
    await detail.getByRole("status").filter({hasText:new RegExp(`相同正文已存在，已更新记录 #${id}`)}).waitFor();
    assert.equal((await (await page.request.get(`${base}/toolbox/prompts?page_size=1`)).json()).total, total);
    assert.deepEqual((await (await page.request.get(`${base}/toolbox/prompts/${id}`)).json()).tags, ["updated-test"]);
    await detail.getByRole("button", {name:"使用此提示词",exact:true}).click();
    assert.equal(await page.evaluate(()=>window.selected), id);
});
