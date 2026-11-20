import { test, before, after } from "node:test";
import assert from "node:assert/strict";
import { createServer } from "node:http";
import { readFile } from "node:fs/promises";
import { once } from "node:events";
import { chromium } from "playwright";

let server, browser, base;
before(async () => {
    const source = await readFile(new URL("../web/js/image_scale_view.mjs", import.meta.url));
    server = createServer((request, response) => {
        response.setHeader("Content-Type", request.url === "/view.mjs" ? "text/javascript" : "text/html");
        response.end(request.url === "/view.mjs" ? source : '<!doctype html><meta charset="utf-8"><body style="background:#17191e"><main style="width:360px;height:340px;margin:40px"></main>');
    });
    server.listen(0, "127.0.0.1"); await once(server, "listening");
    base = `http://127.0.0.1:${server.address().port}`;
    browser = await chromium.launch({headless: true, args: ["--no-sandbox"]});
});
after(async () => { await browser?.close(); await new Promise(resolve => server?.close(resolve)); });

async function fixture(t) {
    const page = await browser.newPage({viewport: {width: 460, height: 450}});
    t.after(() => page.close());
    await page.goto(base);
    await page.evaluate(async () => {
        const {attachScalePreview} = await import("/view.mjs");
        const origin = {id: 1, widgets: [{name: "image", value: "a.png"}], inputs: []};
        window.node = {
            id: 2, size: [360, 450], inputs: [{name: "input", link: 10}],
            graph: {links: {10: {origin_id: 1}}, getNodeById: () => origin},
            widgets: Object.entries({resize_type: "scale by multiplier", "resize_type.multiplier": 2, scale_method: "area", multiple_of: 1}).map(([name, value]) => ({name, value})),
            addDOMWidget(name, type, element, options) {
                document.querySelector("main").append(element);
                const widget = {name, type, options}; this.widgets.push(widget); return widget;
            },
            setSize(value) {this.size = value; this.onResize?.(this.size);}, computeSize: () => [360, 450],
            onExecuted() {window.executed = true;}, onConfigure() {window.configured = true;},
        };
        window.preview = attachScalePreview(node);
        window.set = (name, value) => {node.widgets.find(w => w.name === name).value = value; node.onDrawBackground();};
        window.execute = () => node.onExecuted({toolbox_scale: [{source: [1600, 900], resized: [3200, 1800], output: [3200, 1800], match: null,
            parameters: {resize_type: "scale by multiplier", multiplier: 2}, scale_method: "area", multiple_of: 1}]});
        window.changeInput = () => {origin.widgets[0].value = "b.png"; node.onDrawBackground();};
    });
    return page;
}

test("actual and predicted frames share one scale and distinguish area from edge multipliers", async t => {
    const page = await fixture(t);
    assert.equal(await page.locator('[data-frame="source"]').isVisible(), false);
    await page.evaluate(() => execute());
    assert.match(await page.getByRole("status").textContent(), /实际输出/);
    assert.match(await page.locator(".tb-scale-preview").textContent(), /像素量 ×4/);
    const source = await page.locator('[data-frame="source"]').boundingBox();
    const output = await page.locator('[data-frame="output"]').boundingBox();
    assert.ok(Math.abs(source.width * 2 - output.width) < 1);
    assert.ok(Math.abs(source.height * 2 - output.height) < 1);
    await page.evaluate(() => set("resize_type.multiplier", .5));
    assert.match(await page.getByRole("status").textContent(), /预估/);
    assert.match(await page.locator(".tb-scale-preview").textContent(), /800×450.*0.36 MP/);
    assert.match(await page.locator(".tb-scale-preview").textContent(), /像素量 ×0.25/);
    if (process.env.SCALE_SCREENSHOT) await page.screenshot({path: process.env.SCALE_SCREENSHOT});
    await page.evaluate(() => set("resize_type.multiplier", 2));
    assert.match(await page.getByRole("status").textContent(), /实际输出/);
    assert.equal(await page.evaluate(() => executed), true);
});

test("dynamic mode replacement and final alignment update predictions", async t => {
    const page = await fixture(t);
    await page.evaluate(() => {
        execute();
        node.widgets = node.widgets.filter(w => w.name !== "resize_type.multiplier");
        node.widgets.push({name: "resize_type.megapixels", value: 16});
        set("resize_type", "scale total pixels");
        set("multiple_of", 32);
        node.setSize([210, 450]);
    });
    assert.match(await page.locator(".tb-scale-preview").textContent(), /最终对齐 32/);
    assert.match(await page.locator(".tb-scale-preview").textContent(), /1024²/);
    assert.match(await page.getByRole("status").textContent(), /预估/);
    assert.equal(await page.evaluate(() => node.size[0]), 360);
});

test("editing parameters during execution keeps the returned older result marked as an estimate", async t => {
    const page = await fixture(t);
    await page.evaluate(() => {set("resize_type.multiplier", 3); execute();});
    assert.match(await page.getByRole("status").textContent(), /预估/);
    assert.match(await page.locator(".tb-scale-preview").textContent(), /4800×2700/);
});

test("changed upstream inputs, linked parameters and restored workflows never present stale dimensions as current", async t => {
    const page = await fixture(t);
    await page.evaluate(() => {execute(); changeInput();});
    assert.match(await page.getByRole("status").textContent(), /等待运行/);
    assert.equal(await page.locator('[data-frame="output"]').isVisible(), false);
    await page.evaluate(() => {execute(); node.inputs.push({name: "resize_type.multiplier", link: 11, widget: {name: "resize_type.multiplier"}}); node.onDrawBackground();});
    assert.match(await page.getByRole("status").textContent(), /等待运行/);
    await page.evaluate(() => {execute(); node.onConfigure();});
    assert.equal(await page.evaluate(() => configured), true);
    assert.match(await page.getByRole("status").textContent(), /等待运行/);
    assert.equal(await page.evaluate(() => node.widgets.find(w => w.name === "scale_preview").serializeValue()), undefined);
    assert.equal(await page.locator(".tb-scale-preview img").count(), 0);
});
