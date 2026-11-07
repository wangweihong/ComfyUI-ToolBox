// Exact aspect ratios for metadata filtering; these do not resize any image.
export const SIZE_PRESETS = {
    "9:16": [[720,1280],[864,1536],[1080,1920],[1152,2048],[1440,2560],[2160,3840]],
    "16:9": [[1280,720],[1536,864],[1920,1080],[2048,1152],[2560,1440],[3840,2160]],
    "1:1": [[512,512],[768,768],[1024,1024],[1536,1536],[2048,2048]],
    "4:3": [[640,480],[768,576],[1024,768],[1280,960],[1536,1152],[1920,1440],[2048,1536]],
    "3:4": [[480,640],[576,768],[768,1024],[960,1280],[1152,1536],[1440,1920],[1536,2048],[3072,4096]],
    "2:3": [[512,768],[768,1152],[1024,1536],[1280,1920],[2048,3072]],
    "3:2": [[768,512],[1152,768],[1536,1024],[1920,1280],[3072,2048]],
    "4:5": [[768,960],[1024,1280],[1536,1920],[2048,2560]],
    "5:4": [[960,768],[1280,1024],[1920,1536],[2560,2048]],
};

export const DEFAULT_SIZE = { ratio: "4:3", resolution: "1024x768" };

export function sizeSelection(width, height) {
    const pair = sizeFilter({ enabled:true, ratio:"custom", width, height });
    const ratio = Object.keys(SIZE_PRESETS).find(value => {
        const [x,y] = value.split(":").map(Number);
        return pair.width * y === pair.height * x;
    }) || "custom";
    return { ratio, resolution:`${pair.width}x${pair.height}`, width:pair.width, height:pair.height };
}

export function sizeFilter({ enabled, ratio, resolution, width, height }) {
    if (!enabled) return { match_size: false, width: 1024, height: 768 };
    let pair;
    if (ratio === "custom") pair = [Number(width), Number(height)];
    else if (SIZE_PRESETS[ratio] && /^\d+x\d+$/.test(resolution)) {
        pair = resolution.split("x").map(Number);
        const [x,y] = ratio.split(":").map(Number);
        if (pair[0] * y !== pair[1] * x) pair = undefined;
    }
    if (!pair || pair.some(value => !Number.isInteger(value) || value < 1 || value > 16384)) {
        throw new Error("请选择有效尺寸；自定义宽高需为 1–16384 的整数。");
    }
    return { match_size: true, width: pair[0], height: pair[1] };
}
