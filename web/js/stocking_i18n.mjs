import { STYLE_REGISTRY } from "./stocking_style_registry.mjs?v=20261010-upstream1";
// Stable style IDs and node keys remain unchanged; only visible text is translated.
const EN = {
    "手动强度": "Manual strength", "个部位": "regions", "数值": " value",
    "失败图片处理": "Failed frames", "跳过并报告（默认）": "Skip and report (default)", "立即停止": "Stop immediately", "深度方向": "Depth direction", "白色更近": "White is near", "黑色更近": "Black is near", "深度自动隔开": "Depth barriers",
    "滑杆自动更新草稿预览；保存并关闭后运行工作流得到正式输出。取消不保存参数。整体定位细节，拖动分界线对比原图。": "Sliders update the draft preview. Save and close, then run for final output. Cancel discards parameter changes. Use overview to locate detail and drag divider to compare.",
    "横纹疏密；接近像素大小时会自动限制并衰减。": "Texture spacing; automatically clamped and attenuated near pixel limits.",
    "拖动即切换为手动强度，不影响亮点。": "Dragging switches to manual strength; sparkles are independent.",
    "斜单线的倾斜角度。": "Angle for slanted lines.",
    "按深度分布在鼓起处；需给求解节点连接有效灰度深度图。": "Sparkles on raised surfaces; requires grayscale depth.",
    "沿原画已有高光分布。": "Sparkles along original highlights.",
    "按渲染节点 sparkle_mask 输入分布；未连接时此来源无效。": "Distribution from sparkle_mask; inactive when disconnected.",
    "整个应用区域均匀分布，适合亮片效果。": "Uniform sparkles over the application region.",
    "放弃本次修改并关闭；Esc 也可取消": "Discard draft and close; Esc also cancels", "关闭编辑器（不保存）": "Close editor (discard draft)", "关闭编辑器，不保存本次修改": "Close without saving changes",
    "未提供有效深度：跳过自动隔开与深度亮点": "No valid depth: depth barriers and sparkles skipped",
    "没有目标选区": "No target region", "没有有效走向；请启用基础走向或绘制横向引导": "No valid direction; enable basic direction or draw transverse guides",
    "未改变任何像素：请检查颜色排除、纹理/亮点强度及过密衰减": "No changed pixels: check color exclusion, texture/sparkle strength and attenuation",
    "点选已就绪，当前会话设备选项": "Point selection ready, device", "：首次点击加载本地 SAM；左键添加，右键减去，自动预览推荐范围；选小/中/大后点击“应用选区”。修改模型或设备后重新打开编辑器以准备底图。": ": first click loads local SAM. Left adds, right subtracts. Preview Small/Medium/Large and Apply selection. Reopen editor after model/device changes.",
    "点选不可用：未连接 SAM 模型。请把「tb-丝袜 SAM 点选模型」连接到本节点的 sam 输入，再重新打开编辑器。": "Point selection unavailable: connect the original ViT-B SAM loader to sam and reopen editor.",

    "丝袜纹理 · 编辑与预览": "Stocking texture · Edit and preview", "丝袜纹理预览": "Stocking texture preview", "丝袜引导编辑器": "Stocking guide editor",
    "丝袜引导 · 部位、走向与隔开": "Stocking guides · Regions, direction and barriers", "丝袜纹理 · 选样式、调参数": "Stocking texture · Style and parameters",
    "当前图像": "Current image", "适应": "Fit", "关闭": "Close", "尚未修改": "No changes", "保存并关闭": "Save and close", "取消": "Cancel",
    "画笔 B": "Brush B", "橡皮 E": "Erase E", "走向 P": "Direction P", "隔开 W": "Barrier W", "点选 S": "Point select S", "平移": "Pan",
    "笔刷半径（图像像素）": "Brush radius (image pixels)", "撤销": "Undo", "重做": "Redo", "删除最后走向": "Remove last direction", "删除最后隔开": "Remove last barrier",
    "标出问题": "Diagnostics", "对比原图": "Compare original", "取消等待": "Stop waiting", "正在读取底图…": "Loading source image…",
    "批次引导": "Batch guides", "共享引导": "Shared guides", "逐图引导": "Per-image guides", "部位（靠后者优先）": "Regions (later entries win)",
    "使用输入 MASK 作底图": "Use input MASK", "新增部位": "Add region", "重命名": "Rename", "部位名称": "Region name", "删除部位": "Delete region",
    "原图 / 选区对比": "Original / selection comparison", "对比居中": "Center divider", "原图与选区预览分界": "Original / selection divider", "原图与选区预览对比位置": "Selection comparison position",
    "原图": "Original", "选区预览": "Selection preview", "样式": "Style", "自动强度（按丝袜深浅）": "Automatic strength (fabric brightness)", "自动强度": "Auto strength",
    "颜色排除": "Exclude different colors", "随机种子": "Seed", "细线": "Fine lines", "针织": "Knit loops", "斜单线": "Slanted lines", "加濑风": "Grain knit", "油光（试验）": "Oily (experimental)",
    "密度": "Density", "纹理强度": "Texture strength", "斜度": "Tilt", "按深度亮点": "Depth sparkles", "按画面亮部亮点": "Highlight sparkles", "按遮罩亮点": "Mask sparkles", "均匀分布亮点": "Uniform sparkles",
    "整体 · 点击定位细节，拖分界线对比": "Overview · Click for detail, drag divider to compare", "原图与纹理对比分界": "Original / texture divider", "纹理": "Texture",
    "有未保存修改": "Unsaved changes", "请先新增部位": "Add a region first", "手绘走向": "Manual direction", "基础走向（虚线）+ 手绘优先": "Basic direction (dashed); manual guides take priority",
    "部位": "Regions", "走向": "Direction", "选区来源（未编辑图片逐图处理）": "Region source (unedited images processed independently)",
    "SAM3 语义识别": "SAM3 semantic segmentation", "手工 / 原有点选": "Manual / original point selection", "外部 MASK": "External MASK", "SAM3 提示词": "SAM3 prompt", "识别阈值": "Confidence threshold", "SAM3 识别当前图片": "Segment current image with SAM3",
    "无手绘走向时生成基础走向": "Generate basic direction where manual guides are missing", "导入旧引导并绑定当前图片": "Import legacy guides for this image",
    "纹理效果": "Texture result", "应用语义选区": "Apply semantic regions", "取消语义选区": "Cancel semantic selection",
    "红色：预览将减去的范围（尚未应用）": "Red: area to remove (not applied)", "绿色：预览将添加的范围（尚未应用）": "Green: area to add (not applied)",
    "应用选区": "Apply selection", "取消本次点选": "Cancel point selection", "（推荐）": " (recommended)", "小": "Small", "中": "Medium", "大": "Large",
    "编辑与预览": "Edit and preview", "编辑丝袜引导": "Edit stocking guides", "状态": "Status",
    "打开编辑器即可读取当前底图；SAM3 / 点选 / 画笔": "Open editor to load current image; SAM3 / points / brush",
    "亮点与纹理强度独立，多种来源可混用。深度来源需连接灰度深度图，遮罩来源需连接 sparkle_mask。": "Sparkles and texture strength are independent. Depth requires grayscale input; painted sparkles require sparkle_mask.",
    "排除金边、皮肤等异色；透肤膝盖被误排除时可关闭。": "Exclude trim, skin and different colors. Disable if sheer knees are excluded.",
    "stockings / pantyhose / tights；识别结果先预览，应用后可用原有点选和画笔修边。": "Try stockings / pantyhose / tights. Preview, apply, then refine with original point selection or brush.",
    "语义识别需连接 Easy-Sam3 image 模型；原有 ViT-B 点选和画笔可独立使用。": "Semantic segmentation requires Easy-Sam3 in image mode. Original ViT-B points and brush work independently.",
    "SAM3 语义识别中；可继续画笔编辑，GPU 正式队列忙时等待。": "SAM3 segmentation in progress. Brush remains available; GPU previews wait for the queue.",
    "没有检测到目标；可修改提示词/阈值，或使用原有点选与画笔。": "No target detected. Change prompt/threshold, or use original point selection and brush.",
    "由上游输入控制；预览使用已解析值": "Controlled by upstream input; preview uses resolved value",
    "走向线横穿部位，决定弧度；隔开线画在折叠交界。滚轮缩放，中键或空格拖动平移。修改先保留在草稿中，自动更新预览；保存并关闭后再运行工作流。取消或 Esc 会放弃本次修改。": "Draw transverse direction guides and barriers at folds. Scroll to zoom; middle button or Space to pan. Save and close commits the draft. Cancel or Esc discards it.",
    "拖动滑杆自动预览并写入本渲染节点；关闭后运行工作流得到正式输出。整体点击定位细节，拖分界线对比；细节使用导出的原像素。修改引导后需重新运行工作流。": "Sliders update the draft preview. Save and close, then run for final output. Click overview to locate native-pixel detail; drag divider to compare.",
    "纱线之间的细缝透出暖色亮线，浅色丝袜上呈粉色。": "Warm lines through fine gaps between yarns; pink on light fabric.", "一列列 V 形线圈，接近丝袜加厚部分的织法。": "Columns of V-shaped knit loops.",
    "斜向细线；左右部位方向相反，斜度仅用于此样式。": "Slanted fine lines, opposite directions on left/right. Tilt applies to this style.", "细碎颗粒感的针织纹理。": "Fine grain knit texture.",
    "试验样式，适合有明显高光的纯色深色丝袜；原画高光决定反光位置。": "Experimental. Best on dark plain stockings with existing highlights.",
    "底图": "Source", "图像": "Image", "版本": "Revision", "计算": "Computing", "求解": "Solve", "部位缓存": "Region cache", "命中": "hits", "重算": "recomputed", "未引导": "unguided", "像素": "pixels",
    "周期": "Period", "自动": "Auto", "手动": "Manual", "强度": "strength", "过密衰减": "Frequency attenuation", "已限制过高密度": "Density clamped", "选区": "Selection", "实际变化": "Changed pixels", "未生效": "No effect", "纹理已生效": "Texture applied",
    "细节": "Detail", "拖动平移，滚轮缩放": "Drag to pan, scroll to zoom", "：预览计算中": ": calculating preview", "拖动强度滑杆可切换为手动。": "Drag strength to switch to manual.", "亮点由各来源单独控制。": "Sparkle sources are independent.",
    "检测到": "detected", "个": "", "选择要应用的实例。": "Select instances to apply.", "左腿": "Left leg", "输入遮罩": "Input mask",
    "完成": "complete", "分析中": "processing", "失败": "failed", "设备未报告": "device unavailable", "会话设备": "device", "减去": "remove", "添加": "add",
    "首次点击需加载模型并计算图像 embedding；可继续使用画笔。": "First click loads the model and image embedding; brush remains available.",
    "已预览推荐范围；切换小 / 中 / 大后，点击应用选区。": "Recommended candidate previewed; choose Small / Medium / Large and Apply selection.",
    "模型已移回 CPU。": "Model offloaded to CPU.", "复用图像 embedding": "Reusing image embedding", "可继续绘制或重新点选。": "Continue drawing or retry point selection.",
    "已取消本次点选，已有选区未改变。": "Point selection cancelled; existing regions unchanged.",
    "保存并关闭后写入工作流。": "Save and close to commit to workflow.", "候选": "candidate", "已": "", "数值": "value",
};

for (const style of STYLE_REGISTRY) { EN[style.label] = style.label_en; EN[style.hint] = style.hint_en; }
Object.assign(EN, {
    "基础样式": "Base style", "花纹": "Pattern", "表现模式": "Appearance", "织物": "Fabric", "印花": "Print",
    "花纹大小 %": "Pattern size %", "花纹旋转 °": "Pattern rotation °", "花纹颜色": "Pattern color", "花纹不透明度 %": "Pattern opacity %",
    "英文印花": "English lettering", "启用英文印花": "Enable lettering", "文字预设": "Text preset", "自定义": "Custom", "英文文字": "English text",
    "文字字号 %": "Text size %", "文字列间距 %": "Text column spacing %", "文字行间距 %": "Text row spacing %", "文字旋转 °": "Text rotation °", "文字颜色": "Text color", "文字不透明度 %": "Text opacity %",
    "英文错行重复排列，字母不随左右腿镜像。": "Staggered repeating text; letters are never mirrored between legs.",
    "损伤": "Damage", "启用损伤": "Enable damage", "损伤方式": "Damage placement", "损伤类型": "Damage type", "随机＋手工": "Random + manual", "随机": "Random", "手工": "Manual",
    "钩丝＋抽丝": "Snags + ladders", "梯状抽丝": "Ladder runs", "钩丝 D": "Snags D", "钩丝": "Snags", "每部位随机数量": "Random count per region",
    "损伤长度 %": "Damage length %", "损伤宽度 %": "Damage width %", "损伤强度 %": "Damage strength %", "损伤目标部位": "Damage target region",
    "手工定位损伤": "Draw damage", "删除最后损伤": "Delete last damage", "手工损伤类型": "Manual damage type",
    "点击生成局部损伤，拖动画出路径；右键删除指针附近的损伤。": "Click to create local damage, drag to draw its path; right-click removes the mark near the pointer.",
    "手工损伤请在上游引导编辑器中绘制，保存后重新运行求解节点。": "Draw manual damage in the upstream guide editor, save and rerun the solver.",
    "文字仅支持最多 128 个英文、数字、空格和常见标点；数值必须有效。": "Text supports up to 128 ASCII characters; numeric values must be valid.",
    "预览纹理": "Preview texture", "请先运行渲染节点取得底图": "Run the renderer first to acquire its image",
});

Object.assign(EN, {
 "切开 K":"Cut K", "切线自动贴线":"Snap cut to line art", "自动分割":"Split automatically", "清空选区":"Clear selection", "部位颜色":"Region color",
 "部位（新绘制取得像素归属）":"Regions (new painting claims pixels)", "合并 / 镜像目标":"Merge / mirror target",
 "合并到目标":"Merge into target", "镜像走向到目标":"Mirror direction into target", "横向引导":"Courses", "纵向引导":"Wales", "自动隔开":"Detected barriers",
 "渲染版本":"Renderer version", "兼容旧版":"Legacy compatible", "上游新版 f74c8ac":"Upstream f74c8ac", "透明图层":"Transparent layer",
 "精确替换图层":"Exact replacement layer", "柔和丝袜图层":"Soft stocking layer", "摩尔纹（需要新版与深度）":"Moiré (new renderer and depth required)",
 "摩尔纹强度":"Moiré strength", "摩尔纹面积":"Moiré area", "新版渲染，需要有效深度。":"New renderer; valid depth required.", "从鼓起处向外扩展。":"Expand from each bulge crown.",
 "关联深度 / 亮部亮点":"Link depth / highlight sparkles", "材质预设":"Material presets", "加载预设":"Load preset", "保存 / 覆盖预设":"Save / replace preset", "删除预设":"Delete preset",
 "恢复材质默认":"Reset material defaults", "不可读取":"Unreadable", "导入 PSD 引导":"Import PSD guides", "导出成品":"Export finished PNG", "导出透明 PNG":"Export transparent PNG",
 "导出引导 PSD":"Export guide PSD", "发现未保存草稿":"Unsaved draft found", "恢复草稿":"Recover draft", "丢弃草稿":"Discard draft", "撤销预设 / 默认":"Undo preset / reset",
 "指针附近没有可删除的线":"No removable line near pointer", "已跳过连接输入":"Skipped connected inputs", "镜像完成":"Mirror complete", "轮廓拟合误差":"Outline fit error",
 "Coil 与摩尔纹需选择上游新版。新版油光增加柔光带、暗边与跨遮挡连续高光，仍为试验样式。":"Coil and moiré require the new renderer. New glossy adds soft bands, dark edges and glints across occlusions; still experimental.",
 "摩尔纹需要有效灰度深度图，请连接 depth 输入":"Moiré requires valid grayscale depth; connect depth", "Coil / 摩尔纹需要切换到 upstream_f74c8ac 新版渲染":"Coil / moiré require the upstream_f74c8ac renderer",
 "草稿恢复保存失败；仍可保存节点":"Draft recovery save failed; node saving still works",
});

Object.assign(EN, {
 "基础织物":"Base fabric", "效果图层":"Effect layers", "最终损伤":"Final damage", "材质编辑范围":"Material scope", "全局材质":"Global material", "当前部位":"Current region",
 "全部继承全局":"Inherit all global settings", "独立图层（替换全局）":"Independent layers (replace global stack)", "复制全局图层":"Copy global layers", "覆盖 ":"Override ", "部位材质":"Region material", "编辑部位材质":"Edit region material",
 "添加花纹层":"Add pattern layer", "添加文字层":"Add text layer", "复制层":"Duplicate layer", "删除层":"Delete layer", "上移":"Move up", "下移":"Move down", "启用":"Enabled", "大小 %":"Size %", "旋转 °":"Rotation °", "颜色":"Color", "不透明度 %":"Opacity %", "列间距 %":"Column spacing %", "行间距 %":"Row spacing %", "长度 %":"Length %", "宽度 %":"Width %", "随机数量":"Random count", "继承全局损伤":"Inherit global damage",
 "全局材质由上游输入控制；部位覆盖仍可编辑。":"Global material is controlled by its input; region overrides remain editable.", "请先选择部位":"Select a region first"
});

Object.assign(EN, {
 "滑杆自动更新参数草稿；保存并关闭后写入本渲染节点。取消放弃修改。修改引导后需重新运行求解节点。":"Sliders update the parameter draft. Save and close commits to the renderer; Cancel discards changes. Rerun the solver after editing guides.",
 "关联亮点":"Link sparkles", "启用摩尔纹":"Enable moiré", "相对参考图尺寸的百分比，与基础织纹密度独立。":"Percentage of reference image size, independent of base weave density.",
 "织物结合原图明暗与透肤感；印花保留指定颜色与轮廓。":"Fabric follows image brightness and sheerness; print retains its color and outline.",
 "最多 128 个可打印 ASCII 字符，保留大小写；使用固定字体。":"Up to 128 printable ASCII characters; case preserved with the bundled font.",
 "每层独立的不透明度；颜色与不透明度变化复用采样缓存。":"Independent opacity per layer; color and opacity changes reuse sampling.",
 "沿部位全图坐标旋转，文字不随左右腿镜像。":"Rotate along full-image region coordinates; letters never mirror between legs."
});

export function translate(text, locale = "zh") {
    if (!String(locale).toLowerCase().startsWith("en")) return text;
    if (EN[text] !== undefined) return EN[text];
    let result = String(text);
    for (const [zh, en] of Object.entries(EN).sort((a, b) => b[0].length - a[0].length)) if (zh.length > 1) result = result.split(zh).join(en);
    return result.replaceAll("：", ": ").replaceAll("；", "; ");
}

export function localizeDialog(root, locale) {
    if (!String(locale).startsWith("en")) return { disconnect() {} };
    const apply = () => {
        const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
        while (walker.nextNode()) {
            const node = walker.currentNode, translated = translate(node.nodeValue, locale);
            if (node.nodeValue !== translated) node.nodeValue = translated;
        }
        for (const node of root.querySelectorAll("[title], [aria-label]")) for (const key of ["title", "aria-label"]) {
            const raw = node.getAttribute(key); if (raw) node.setAttribute(key, translate(raw, locale));
        }
    };
    apply();
    const observer = new MutationObserver(() => { observer.disconnect(); apply(); observer.observe(root, { childList: true, subtree: true, characterData: true }); });
    observer.observe(root, { childList: true, subtree: true, characterData: true });
    return observer;
}
