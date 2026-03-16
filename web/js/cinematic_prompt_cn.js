// !!! CRITICAL FIX: Added extra "../" to reach the root folder from "web/js/"
import { app } from "../../../scripts/app.js";

// --- CSS STYLES ---
const style = `
<style>
    /* Main Container */
    .yedp-container {
        --bg-dark: #1e1e1e;
        --bg-panel: #252526;
        --bg-input: #333333;
        --bg-hover: #3e3e42;
        --text-main: #e0e0e0;
        --text-muted: #858585;
        --accent: #F5C518; /* IMDb/Cinema Gold */
        --border: #444444;
        --radius: 6px;
        font-family: 'Inter', sans-serif;
        color: var(--text-main);
        background: var(--bg-dark);
        display: flex;
        flex-direction: column;
        width: 100%;
        height: 100%;
        min-height: 200px; /* CHANGED: Reduced from 600px to allow vertical scaling */
        overflow: hidden;
        border-radius: 8px;
        font-size: 12px;
        border: 1px solid var(--border);
        box-shadow: 0 4px 12px rgba(0,0,0,0.5);
    }
    
    .yedp-layout { display: flex; height: 100%; }
    
    /* Left Sidebar */
    .yedp-sidebar { 
        width: 35%; 
        min-width: 140px; /* CHANGED: Reduced from 200px to keep proportions when scaling down */
        background: var(--bg-panel); 
        border-right: 1px solid var(--border); 
        overflow-y: auto; 
        padding: 15px; 
        flex-shrink: 0; 
        display: flex;
        flex-direction: column;
        gap: 12px;
    }

    /* Right Preview Area */
    .yedp-main { 
        flex: 1; 
        padding: 20px; 
        overflow-y: auto; 
        background: #111; 
        display: flex; 
        flex-direction: column; 
        gap: 15px; 
    }

    .yedp-label { 
        font-size: 0.7rem; 
        font-weight: 800; 
        color: var(--accent); 
        text-transform: uppercase; 
        letter-spacing: 0.5px;
        margin-bottom: 4px;
        display: block; 
    }

    .yedp-input, .yedp-textarea { 
        background: var(--bg-input); 
        border: 1px solid var(--border); 
        color: var(--text-main); 
        padding: 8px; 
        border-radius: var(--radius); 
        width: 100%; 
        font-size: 12px;
    }
    .yedp-textarea { resize: vertical; min-height: 40px; font-family: sans-serif; }
    .yedp-input:focus, .yedp-textarea:focus { border-color: var(--accent); outline: none; }

    .yedp-btn { 
        background: var(--bg-input); 
        border: 1px solid transparent; 
        color: var(--text-muted); 
        padding: 8px 10px; 
        cursor: pointer; 
        border-radius: 4px; 
        width: 100%; 
        text-align: left; 
        transition: all 0.1s;
        display: flex;
        justify-content: space-between;
        align-items: center;
    }
    .yedp-btn:hover { background: var(--bg-hover); color: var(--text-main); }
    .yedp-btn.active { 
        border-color: var(--accent); 
        color: var(--accent); 
        background: rgba(245, 197, 24, 0.05); 
        font-weight: bold;
    }

    .yedp-grid { display: grid; grid-template-columns: repeat(2, 1fr); gap: 6px; }
    .yedp-grid-item { 
        background: var(--bg-input); 
        border: 1px solid transparent; 
        padding: 8px; 
        text-align: center; 
        cursor: pointer; 
        border-radius: 4px; 
        font-size: 0.75rem; 
        transition: all 0.1s;
    }
    .yedp-grid-item:hover { background: var(--bg-hover); }
    .yedp-grid-item.active { border-color: var(--accent); background: rgba(245, 197, 24, 0.1); color: var(--accent); }

    .yedp-slider-wrapper { padding: 5px 0; }
    .yedp-slider-header { display: flex; justify-content: space-between; margin-bottom: 5px; color: var(--accent); font-weight: bold; }
    .yedp-range { width: 100%; cursor: pointer; accent-color: var(--accent); }
    .yedp-slider-labels { display: flex; justify-content: space-between; font-size: 0.65rem; color: var(--text-muted); margin-top: 2px; }

    .yedp-preview-box { 
        width: 100%; 
        height: 250px; 
        background: #000; 
        border: 1px solid var(--border); 
        display: flex; 
        align-items: center; 
        justify-content: center; 
        overflow: hidden; 
        position: relative; 
        border-radius: 4px;
    }
    .yedp-preview-img { 
        max-width: 100%; 
        max-height: 100%; 
        object-fit: contain; 
        display: block; 
        opacity: 0;
        transition: opacity 0.3s;
    }
    .yedp-preview-img.loaded { opacity: 1; }
    
    .yedp-preview-overlay {
        position: absolute;
        bottom: 10px;
        background: rgba(0,0,0,0.8);
        color: var(--accent);
        padding: 4px 8px;
        border-radius: 4px;
        font-size: 0.8rem;
    }

    .yedp-info-box {
        background: rgba(245, 197, 24, 0.05);
        border-left: 3px solid var(--accent);
        padding: 12px;
        border-radius: 4px;
        min-height: 60px;
        margin-bottom: 10px;
    }
    .yedp-info-title { color: var(--accent); font-weight: bold; font-size: 0.9rem; display: block; margin-bottom: 4px; }
    .yedp-info-text { color: #ccc; font-size: 0.8rem; line-height: 1.4; }

    .yedp-output { 
        width: 100%; 
        height: 80px; 
        background: #0a0a0a; 
        border: 1px solid var(--border); 
        color: #fff; 
        padding: 10px; 
        font-family: 'Consolas', monospace; 
        font-size: 0.85rem; 
        border-radius: 4px;
    }
    .yedp-output:focus { border-color: var(--accent); box-shadow: 0 0 5px rgba(245, 197, 24, 0.3); outline: none; }

    .yedp-actions { margin-top: auto; display: flex; gap: 10px; }
    .yedp-btn-action { 
        background: var(--bg-input); 
        color: var(--text-main); 
        border: 1px solid var(--border); 
        padding: 10px; 
        border-radius: 4px; 
        cursor: pointer; 
        font-weight: bold; 
        flex: 1; 
        text-align: center;
        transition: all 0.2s;
    }
    .yedp-btn-action:hover { background: var(--bg-hover); }
    .yedp-btn-primary { background: var(--accent); color: #000; border: none; }
    .yedp-btn-primary:hover { background: #d4a017; }
    .yedp-btn-reset { background: #333; color: #aaa; border: 1px solid #555; }
    .yedp-btn-reset:hover { background: #444; color: #fff; }
</style>
`;

const ASSET_PATH = new URL("../assets/cinematic/", import.meta.url).href; 
const ASSET_EXT = ".jpg";

// --- FULL DATA DEFINITIONS ---
// --- FULL DATA DEFINITIONS ---

const categories = {
  ratio: {
    title: "宽高比", type: "ratio",
    options: [
      {id:"16-9", label:"16:9", value:"--ar 16:9", desc:"标准宽屏。适合电视和YouTube。", w:16, h:9},
      {id:"9-16", label:"9:16", value:"--ar 9:16", desc:"垂直。适合TikTok、Reels和手机。", w:9, h:16},
      {id:"1-1", label:"1:1", value:"--ar 1:1", desc:"正方形。经典Instagram格式。", w:1, h:1},
      {id:"4-3", label:"4:3", value:"--ar 4:3", desc:"标清。复古电视风格。", w:4, h:3},
      {id:"235-1", label:"2.35:1", value:"--ar 2.35:1", desc:"变形宽银幕。经典CinemaScope风格。", w:2.35, h:1},
      {id:"143-1", label:"1.43:1", value:"--ar 1.43:1", desc:"IMAX。巨大的垂直感。", w:1.43, h:1}
    ]
  },
  framing: {
    title: "取景/镜头尺寸", type: "select",
    options: [
      {id:"ecu", label:"极特写", value:"extreme close-up", desc:"聚焦特定细节（如眼睛）。增强情感。"},
      {id:"cu", label:"特写", value:"close-up", desc:"头和肩。聚焦面部表情。"},
      {id:"med", label:"中景", value:"medium shot", desc:"腰部以上。标准互动镜头。"},
      {id:"cowboy", label:"牛仔镜头", value:"American shot", desc:"大腿中部以上。源自西部片以展示枪套。"},
      {id:"full", label:"全身", value:"full body shot", desc:"从头到脚。展示服装和姿态。"},
      {id:"wide", label:"广角镜头", value:"wide shot", desc:"主体+环境。展示上下文。"},
      {id:"est", label:"定场镜头", value:"establishing shot", desc:"非常广。设定场景和地点。"},
      {id:"macro", label:"微距", value:"macro photography", desc:"微观细节。昆虫、纹理、眼睛。"},
      {id:"tilt", label:"移轴", value:"tilt-shift photography", desc:"选择性聚焦带的微缩效果。使大场景看起来像模型。"},
      {id:"split", label:"分像屈光", value:"split diopter shot", desc:"前景和背景都清晰。经典的布莱恩·德·帕尔玛技巧。"}
    ]
  },
  angle: {
    title: "拍摄角度", type: "select",
    options: [
      {id:"eye", label:"平视", value:"eye level angle", desc:"中性视角。直接与主体连接。"},
      {id:"low", label:"低角度", value:"low angle shot", desc:"仰视。使主体显得强大或支配性。"},
      {id:"high", label:"高角度", value:"high angle shot", desc:"俯视。使主体显得脆弱或渺小。"},
      {id:"worm", label:"虫眼视角", value:"worm's eye view", desc:"从地面仰视。宏伟或奇异。"},
      {id:"ground", label:"地面水平", value:"ground level shot", desc:"相机放在地面。亲密的纹理。"},
      {id:"bird", label:"鸟瞰/俯视", value:"overhead bird's eye view", desc:"正上方（90度）。几何和布局。"},
      {id:"ots", label:"过肩镜头", value:"over-the-shoulder shot", desc:"一个角色背后看另一个角色。对话。"},
      {id:"dutch", label:"荷兰角", value:"Dutch angle", desc:"倾斜地平线。制造不安、紧张或迷失感。"},
      {id:"pov", label:"第一人称视角", value:"first-person POV", desc:"通过角色的眼睛看。"}
    ]
  },
  camera: {
    title: "相机型号", type: "select",
    options: [
      {id:"arri", label:"Arri Alexa LF", value:"shot on Arri Alexa LF", desc:"数字电影行业标准。高动态范围。"},
      {id:"imax70", label:"IMAX 70mm Film", value:"shot on IMAX 70mm Film", desc:"无与伦比的分辨率和深度。诺兰风格。"},
      {id:"panavision", label:"Panavision Millennium", value:"shot on Panavision Millennium DXL2", desc:"温暖的肤色和经典好莱坞美学。"},
      {id:"sony", label:"Sony Venice 2", value:"shot on Sony Venice 2", desc:"现代、锐利、出色的低光性能。"},
      {id:"iphone", label:"iPhone 15 Pro", value:"shot on iPhone 15 Pro", desc:"数字、锐利、深景深。现代vlog风格。"},
      {id:"polaroid", label:"Polaroid SX-70", value:"Polaroid SX-70 instant film", desc:"柔和、怀旧、化学边框和褪色。"},
      {id:"gopro", label:"GoPro Hero", value:"shot on GoPro Hero", desc:"广角、畸变鱼眼、运动感。"}
    ]
  },
  focal: {
    title: "焦距", type: "select",
    options: [
      {id:"14mm", label:"14mm（超广角）", value:"14mm lens", desc:"边缘畸变、巨大视野。运动相机感。"},
      {id:"24mm", label:"24mm（广角）", value:"24mm lens", desc:"标准广角。适合风景和室内。"},
      {id:"35mm", label:"35mm（经典）", value:"35mm lens", desc:"最接近人眼视野。叙事镜头。"},
      {id:"50mm", label:"50mm（标准）", value:"50mm lens", desc:"经典五十。自然视角，无畸变。"},
      {id:"85mm", label:"85mm（人像）", value:"85mm lens", desc:"美化面部。使主体与背景分离。"},
      {id:"135mm", label:"135mm（长焦）", value:"135mm lens", desc:"显著压缩。适合远距离主体。"},
      {id:"200mm", label:"200mm（超长焦）", value:"200mm lens", desc:"压缩空间。背景在主体后显得巨大。"}
    ]
  },
  dof: {
    title: "光圈/景深", type: "slider",
    options: [
      {id:"f12", val:"f/1.2", label:"f/1.2（梦幻）", desc:"极浅焦点。梦幻散景。"},
      {id:"f18", val:"f/1.8", label:"f/1.8（浅）", desc:"非常浅。适合低光。"},
      {id:"f28", val:"f/2.8", label:"f/2.8（专业）", desc:"专业变焦镜头标准。良好的分离度。"},
      {id:"f4", val:"f/4.0", label:"f/4.0（平衡）", desc:"分离度和清晰度平衡。"},
      {id:"f56", val:"f/5.6", label:"f/5.6（锐利）", desc:"标准锐度。"},
      {id:"f8", val:"f/8.0", label:"f/8.0（风景）", desc:"风景标准。大部分清晰。"},
      {id:"f11", val:"f/11", label:"f/11（深）", desc:"深景深。"},
      {id:"f16", val:"f/16", label:"f/16（非常锐利）", desc:"一切清晰。出现星芒。"},
      {id:"f22", val:"f/22", label:"f/22（最大景深）", desc:"最大景深。可能有衍射模糊风险。"}
    ]
  },
  lighting: {
    title: "照明", type: "select",
    options: [
      {id:"volumetric", label:"体积光/上帝光", value:"volumetric lighting", desc:"空气中可见的光束。史诗氛围。"},
      {id:"biolum", label:"生物荧光", value:"bioluminescent lighting", desc:"发光的有机光（蓝/绿）。阿凡达潘多拉风格。"},
      {id:"golden", label:"黄金时刻", value:"golden hour", desc:"日落前的温暖柔和光。"},
      {id:"blue", label:"蓝色时刻", value:"blue hour", desc:"日出前的冷、忧郁光线。"},
      {id:"noon", label:"正午阳光", value:"harsh noon sunlight", desc:"强烈的正午阳光，短阴影，高对比，明亮。"},
      {id:"overcast", label:"阴天", value:"overcast soft lighting", desc:"漫射，无阴影，巨型柔光箱效果。"},
      {id:"studio", label:"影棚主光", value:"studio key lighting", desc:"受控的专业人工照明。"},
      {id:"rembrandt", label:"伦勃朗光", value:"Rembrandt lighting", desc:"脸颊上的三角形光。戏剧性肖像。"},
      {id:"candle", label:"烛光", value:"lit by candlelight", desc:"温暖、闪烁、低光、亲密。"},
      {id:"moon", label:"月光", value:"moonlight", desc:"冷、银/蓝色低光。"},
      {id:"sil", label:"剪影", value:"silhouette lighting", desc:"主体在明亮背景前呈黑色。"},
      {id:"neon", label:"霓虹", value:"neon lighting", desc:"鲜艳的粉红、青色和强烈的人工光。"},
      {id:"chiaroscuro", label:"明暗对比", value:"chiaroscuro", desc:"光和暗之间高对比。"}
    ]
  },
  palette: {
    title: "色彩调色板", type: "select",
    options: [
      {id:"tealorange", label:"青橙", value:"teal and orange color grading", desc:"大片标准。冷阴影，温暖肤色。"},
      {id:"velvia", label:"富士Velvia", value:"Fujifilm Velvia 50", desc:"高饱和度，深黑，鲜艳色彩。自然摄影。"},
      {id:"ektachrome", label:"柯达Ektachrome", value:"Kodak Ektachrome", desc:"冷色调，细颗粒，独特蓝色。"},
      {id:"techni", label:"特艺彩色", value:"Technicolor process", desc:"超饱和红/绿/蓝。老好莱坞《绿野仙踪》风格。"},
      {id:"bw", label:"黑白", value:"black and white photography", desc:"永恒，聚焦纹理和光线。"},
      {id:"kodak", label:"柯达Portra 400", value:"Kodak Portra 400 film look", desc:"自然肤色，细颗粒，温暖高光。"},
      {id:"vivid", label:"鲜艳/饱和", value:"vivid colors, high saturation", desc:"有力、明亮、引人注目。"},
      {id:"muted", label:"柔和/低饱和", value:"muted tones, low saturation", desc:"阴沉、严肃、现实。"},
      {id:"warm", label:"暖色调", value:"warm color palette", desc:"舒适、怀旧、安全。"},
      {id:"cool", label:"冷色调", value:"cool color palette", desc:"冷静、疏离或悲伤。"},
      {id:"highcon", label:"高对比", value:"high contrast", desc:"深黑和亮白。戏剧性。"},
      {id:"mono", label:"单色", value:"monochromatic color scheme", desc:"使用单一颜色的深浅。"},
      {id:"neonpal", label:"霓虹色调", value:"neon color palette", desc:"电光绿、粉、紫。"},
      {id:"sepia", label:"怀旧棕褐", value:"sepia tone", desc:"老西部、闪回、古旧。"}
    ]
  },
  texture: {
    title: "纹理与后期（多选）", type: "multi",
    options: [
      {id:"clean", label:"干净数字", value:"clean digital noise-free", desc:"原始数字清晰度。无噪点或伪影。"},
      {id:"grain", label:"胶片颗粒", value:"heavy film grain", desc:"胶片上卤化银晶体的有机纹理。"},
      {id:"burn", label:"胶片烧灼", value:"film burn artifacts", desc:"卷片边缘的漏光和化学变形。"},
      {id:"vhs", label:"VHS录像带", value:"VHS artifacts", desc:"模拟跟踪错误和磁带颜色渗漏。"},
      {id:"bloom", label:"辉光", value:"bloom effect", desc:"从明亮边缘扩散的光，创造梦幻光芒。"},
      {id:"chromatic", label:"色差", value:"chromatic aberration", desc:"镜头折射引起的高对比边缘色边。"},
      {id:"motion", label:"运动模糊", value:"motion blur", desc:"通过较慢快门速度捕捉的动能。"},
      {id:"vignette", label:"暗角", value:"vignette", desc:"向角落逐渐变暗，聚焦视线。"}
    ]
  },
  style: {
    title: "艺术风格（多选）", type: "multi",
    options: [
      {id:"photo", label:"照片级真实", value:"photorealistic, 8k", desc:"以物理准确性模仿真实摄影。"},
      {id:"cine", label:"电影感", value:"cinematic composition", desc:"专业电影拍摄的典型情绪和灯光。"},
      {id:"3d", label:"3D渲染", value:"Unreal Engine 5 render, 3D", desc:"现代实时计算机图形的锐利、干净外观。"},
      {id:"clay", label:"黏土动画", value:"claymation style, Aardman", desc:"定格黏土角色的触感、手工感。"},
      {id:"water", label:"水彩", value:"watercolor painting", desc:"柔和边缘，颜色渗透，有机纸纹理。"},
      {id:"cyber", label:"赛博朋克", value:"Cyberpunk aesthetic", desc:"高科技低生活；霓虹、雨水和城市未来主义。"},
      {id:"steam", label:"蒸汽朋克", value:"Steampunk aesthetic, brass and gears", desc:"维多利亚工业设计，由蒸汽和发条驱动。"},
      {id:"diner", label:"1950年代餐厅", value:"1950s diner aesthetic, retro americana", desc:"铬合金、霓虹、棋盘地板和经典美国怀旧。"},
      {id:"atom", label:"原子朋克", value:"atompunk aesthetic", desc:"1950年代的复古未来主义愿景：Googie建筑和核乐观主义。"},
      {id:"vapor", label:"蒸汽波", value:"vaporwave aesthetic", desc:"复古未来主义80年代梦境，粉红和青绿调。"},
      {id:"goth", label:"哥特", value:"Gothic aesthetic", desc:"黑暗、华丽、神秘氛围，源于历史建筑。"},
      {id:"min", label:"极简主义", value:"minimalist style", desc:"剥离到基本形状、颜色和概念。"},
      {id:"retro80", label:"80年代复古", value:"1980s retro style", desc:"饱和原色和CRT屏幕的低保真辉光。"},
      {id:"docu", label:"写实纪录片", value:"gritty documentary footage", desc:"原始、未经修饰、手持摄影的现实主义。"},
      {id:"ghibli", label:"吉卜力工作室", value:"Studio Ghibli style", desc:"丰富的手绘背景和奇幻魅力。"},
      {id:"oil", label:"油画", value:"oil painting texture", desc:"厚笔触和画布上丰富、分层的颜料。"},
      {id:"noir", label:"黑色电影", value:"film noir style", desc:"高对比照明和愤世嫉俗的城市氛围。"}
    ]
  },
  artist: {
    title: "艺术家/导演", type: "select",
    options: [
      {id:"wes", label:"韦斯·安德森", value:"directed by Wes Anderson", desc:"对称、柔和色彩和奇幻故事书式舞台。"},
      {id:"ridley", label:"雷德利·斯科特", value:"directed by Ridley Scott", desc:"氛围规模、高细节和阴郁科幻黑色。"},
      {id:"nolan", label:"克里斯托弗·诺兰", value:"directed by Christopher Nolan", desc:"宏大尺度、实景特效和冷静、干净的色调。"},
      {id:"hopper", label:"爱德华·霍普", value:"art by Edward Hopper", desc:"戏剧性阴影、城市孤立和电影般的静止。"},
      {id:"fraser", label:"格雷格·弗莱瑟", value:"cinematography by Greig Fraser", desc:"《蝙蝠侠》《沙丘》风格：阴郁、柔和、聚焦黑暗的数字摄影。"},
      {id:"lubezki", label:"艾曼努尔·卢贝兹基", value:"cinematography by Emmanuel Lubezki", desc:"自然光大师和沉浸式长镜头摄影。"},
      {id:"hoyte", label:"霍伊特·范·霍特玛", value:"cinematography by Hoyte van Hoytema", desc:"IMAX规模、触感纹理和浅景深。"},
      {id:"fincher", label:"大卫·芬奇", value:"directed by David Fincher", desc:"极致精确、绿/黄调、低光数字清晰度。"},
      {id:"burton", label:"蒂姆·伯顿", value:"directed by Tim Burton", desc:"哥特、古怪、黑暗奇幻视觉，高对比。"},
      {id:"spielberg", label:"史蒂文·斯皮尔伯格", value:"directed by Steven Spielberg", desc:"电影奇观、背光和鲜明标志性剪影。"},
      {id:"denis", label:"丹尼斯·维伦纽瓦", value:"directed by Denis Villeneuve", desc:"粗野主义建筑、巨大规模和沉重氛围。"},
      {id:"wong", label:"王家卫", value:"directed by Wong Kar-wai", desc:"饱和霓虹、运动模糊和都市向往感。"},
      {id:"mead", label:"西德·米德", value:"art by Syd Mead", desc:"工业未来主义和实用高科技设计。"},
      {id:"miyazaki", label:"宫崎骏", value:"art by Hayao Miyazaki", desc:"丰富自然、复杂飞行器和手绘细节。"},
      {id:"tarantino", label:"昆汀·塔伦蒂诺", value:"directed by Quentin Tarantino", desc:"低角度、鲜艳色彩和70年代剥削电影风格。"},
      {id:"giger", label:"H.R.吉格尔", value:"art by H.R. Giger", desc:"生物机械噩梦纹理和单色黑暗。"}
    ]
  }
};

// --- HELPER: UPDATE PREVIEW ---
// Shared helper function to update the visual reference monitor
const updatePreviewLogic = (container, catKey, id, nodeTypeStr, node) => {
    const img = container.querySelector(".yedp-preview-img");
    const infoTitle = container.querySelector(".yedp-info-title");
    const infoText = container.querySelector(".yedp-info-text");
    
    if(!img) return;

    let opt;
    if(catKey === 'dof') opt = categories.dof.options[id];
    else opt = categories[catKey]?.options?.find(o=>o.id === id);

    if (!opt) return;

    if(infoTitle && infoText) {
        infoTitle.innerText = opt.label;
        infoText.innerText = opt.desc || "";
    }

    // SKIP RATIO FOR PREVIEW (Loader Logic uses this to skip invalid loads)
    if (categories[catKey].type === 'ratio') return; 

    // !!! MODIFIED SECTION: Removed the widget update block from here. 
    // This ensures hovering only updates the image preview, not the node output value.

    img.classList.remove("loaded");
    const cb = "?t=" + new Date().getTime();
    const filenameBase = `${catKey}_${opt.id}`;
    
    img.onload = () => img.classList.add("loaded");
    img.onerror = function() {
        const currentSrc = this.src;
        if (currentSrc.includes(".jpg")) this.src = ASSET_PATH + filenameBase + ".png" + cb;
        else if (currentSrc.includes(".png")) this.src = ASSET_PATH + filenameBase + ".jpeg" + cb;
        else {
            this.src = `https://placehold.co/400x300/222/666?text=${catKey}:${opt.id}`;
            this.classList.add("loaded");
            this.onerror = null;
        }
    };
    img.src = ASSET_PATH + filenameBase + ".jpg" + cb;
};


// 1. PROMPT BUILDER UI
function createPromptBuilderUI(node) {
    node.bgcolor = "#222"; 
    
    // Hide Widgets
    if (node.widgets) {
        for (let w of node.widgets) {
            w.type = "hidden"; 
            w.computeSize = () => [0, -4]; 
        }
    }

    node.defaultState = {
        mode: "stablediffusion", ratio: "16-9", camera: "arri", framing: "wide",
        angle: "eye", focal: "50mm", dof: 2, lighting: "volumetric", palette: "tealorange",
        texture: [], style: ["photo", "cine"], artist: "wes",
        subject: "A lone astronaut", negative: ""
    };
    node.state = Object.assign({}, node.defaultState);

    const container = document.createElement("div");
    container.className = "yedp-container";
    container.innerHTML = `${style}<div class="yedp-layout" style="color:#666; justify-content:center; align-items:center;">Loading Prompt Builder...</div>`;

    const updateOutputs = () => {
        const widgets = node.widgets;
        if (!widgets) return;

        const p = node.state;
        const posOut = container.querySelector(".positive-output");
        if(!posOut) return;

        const getVal = (cat, id) => categories[cat]?.options?.find(o => o.id === id)?.value || "";
        
        const cam = getVal('camera', p.camera);
        const frame = getVal('framing', p.framing);
        const ang = getVal('angle', p.angle);
        const focal = getVal('focal', p.focal);
        const light = getVal('lighting', p.lighting);
        const pal = getVal('palette', p.palette);
        const artist = getVal('artist', p.artist);
        
        const styles = (p.style || []).map(s => getVal('style', s)).join(", ");
        const textures = (p.texture || []).map(t => getVal('texture', t)).join(", ");
        
        const dofObj = categories.dof.options[p.dof];
        const dofVal = dofObj ? dofObj.val : "";
        const ratio = categories.ratio.options.find(o => o.id === p.ratio)?.value || "";

        let final = "";
        const parts = [];
        
        if (p.mode === 'flux' || p.mode === 'nanobanana') {
                const prefix = p.mode === 'nanobanana' ? "High-end cinematic photography: " : "";
                let sentence = `${prefix}`;
                if (frame) sentence += `${frame} of ${p.subject}`;
                else sentence += `${p.subject}`; 
                
                if (ang) sentence += `, shot at ${ang}`;
                
                if (cam) {
                    if (cam.toLowerCase().startsWith("shot on")) sentence += `, ${cam}`;
                    else sentence += ` on ${cam}`;
                }
                
                if (focal) sentence += ` with a ${focal}`;
                if (dofVal) sentence += ` at aperture ${dofVal}`;
                
                if (light) sentence += `. The lighting is ${light}`;
                if (pal) sentence += ` with ${pal} color grade`;
                
                if (artist) {
                    if (artist.toLowerCase().startsWith("directed by") || artist.toLowerCase().startsWith("art by")) {
                        sentence += `. ${artist}`;
                    } else {
                        sentence += `. In the style of ${artist}`;
                    }
                }

                if (styles) sentence += `. Visuals: ${styles}`;
                if (textures) sentence += `. ${textures}`;
                if (ratio) sentence += `. ${ratio}`;

                final = sentence;
                final = final.replace(/\.\./g, '.').replace(/\s+/g, ' ').trim();
                
        } else if (p.mode === 'midjourney') {
            if(styles) parts.push(styles);
            if(frame) parts.push(`${frame} of ${p.subject}`); else parts.push(`${p.subject}`);
            if(cam) parts.push(cam);
            if(focal) parts.push(focal);
            if(dofVal) parts.push(dofVal); 
            if(ang) parts.push(ang);
            if(light) parts.push(light);
            if(pal) parts.push(pal);
            if(artist) parts.push(artist);
            if(textures) parts.push(textures);
            final = parts.filter(x=>x).join(", ") + (ratio ? " " + ratio : "");
        } else {
            if(styles) parts.push(styles);
            if(frame) parts.push(`${frame} of ${p.subject}`); else parts.push(`${p.subject}`);
            if(cam) parts.push(cam);
            if(focal) parts.push(focal);
            if(dofVal) parts.push(`aperture ${dofVal}`);
            if(ang) parts.push(ang);
            if(light) parts.push(light);
            if(pal) parts.push(pal);
            if(artist) parts.push(artist);
            if(textures) parts.push(textures);
            final = parts.filter(x=>x).join(", ");
        }
        
        posOut.value = final;
        if(widgets[0]) widgets[0].value = JSON.stringify(p);
        if(widgets[1]) widgets[1].value = final;
        if(widgets[2]) widgets[2].value = p.negative;
    };

    const updatePreview = (catKey, id) => {
        updatePreviewLogic(container, catKey, id, "prompt", node);
    };

    const renderControls = () => {
        const controlsArea = container.querySelector(".dynamic-controls");
        if(!controlsArea) return; 
        controlsArea.innerHTML = "";
        
        Object.keys(categories).forEach(key => {
            const cat = categories[key];
            const label = document.createElement("div");
            label.className = "yedp-label";
            label.innerText = cat.title;
            controlsArea.appendChild(label);
            const wrapper = document.createElement("div");
            
            if (cat.type === 'slider') {
                wrapper.className = "yedp-slider-wrapper";
                const header = document.createElement("div");
                header.className = "yedp-slider-header";
                const valSpan = document.createElement("span");
                valSpan.innerText = cat.options[node.state[key]].label;
                header.appendChild(valSpan);
                wrapper.appendChild(header);
                
                const range = document.createElement("input");
                range.type = "range"; range.min = 0; range.max = cat.options.length - 1;
                range.value = node.state[key]; range.className = "yedp-range";
                range.oninput = (e) => {
                    const idx = parseInt(e.target.value);
                    node.state[key] = idx;
                    valSpan.innerText = cat.options[idx].label;
                    updateOutputs();
                    updatePreview(key, idx); 
                };
                wrapper.appendChild(range);
                const labels = document.createElement("div");
                labels.className = "yedp-slider-labels";
                labels.innerHTML = "<span>Blurry</span><span>Sharp</span>";
                wrapper.appendChild(labels);
            } else if (cat.type === 'ratio' || cat.type === 'multi') {
                wrapper.className = "yedp-grid";
                cat.options.forEach(opt => {
                    const btn = document.createElement("div");
                    const isActive = cat.type === 'multi' 
                        ? (node.state[key] && node.state[key].includes(opt.id))
                        : (node.state[key] === opt.id);
                        
                    btn.className = `yedp-grid-item ${isActive ? 'active' : ''}`;
                    btn.innerText = opt.label;
                    btn.onclick = () => {
                        if(cat.type === 'multi') {
                            if(!node.state[key]) node.state[key] = [];
                            if(node.state[key].includes(opt.id)) 
                                node.state[key] = node.state[key].filter(x => x !== opt.id);
                            else node.state[key].push(opt.id);
                        } else {
                            if (node.state[key] === opt.id) node.state[key] = "";
                            else node.state[key] = opt.id;
                        }
                        renderControls(); updatePreview(key, opt.id); updateOutputs();
                    };
                    btn.onmouseenter = () => updatePreview(key, opt.id);
                    wrapper.appendChild(btn);
                });
            } else {
                wrapper.style.display = "flex"; wrapper.style.flexDirection = "column"; wrapper.style.gap = "4px";
                cat.options.forEach(opt => {
                    const btn = document.createElement("div");
                    const isActive = node.state[key] === opt.id;
                    btn.className = `yedp-btn ${isActive ? 'active' : ''}`;
                    btn.innerHTML = `<span>${opt.label}</span> ${isActive ? '●' : ''}`;
                    btn.onmouseenter = () => updatePreview(key, opt.id);
                    btn.onclick = () => {
                        if (node.state[key] === opt.id) node.state[key] = "";
                        else node.state[key] = opt.id;
                        renderControls(); updateOutputs();
                    };
                    wrapper.appendChild(btn);
                });
            }
            controlsArea.appendChild(wrapper);
        });
    };

    const buildUI = () => {
        container.innerHTML = `
            ${style}
            <div class="yedp-layout">
                <div class="yedp-sidebar">
                    <div class="yedp-label">Formatting Mode</div>
                    <select class="yedp-input mode-select">
                        <option value="midjourney">Midjourney</option>
                        <option value="stablediffusion">Stable Diffusion</option>
                        <option value="flux">Flux</option>
                        <option value="nanobanana">NanoBanana Pro</option>
                    </select>

                    <div class="yedp-label">Subject</div>
                    <input type="text" class="yedp-input subject-input" placeholder="A lone astronaut..." value="${node.state.subject}">

                    <div class="yedp-label">Negative</div>
                    <textarea class="yedp-textarea negative-input" placeholder="blurry, low quality...">${node.state.negative}</textarea>

                    <div class="dynamic-controls"></div>
                </div>
                
                <div class="yedp-main">
                    <div class="yedp-label">Visual Reference</div>
                    <div class="yedp-preview-box">
                        <img class="yedp-preview-img" src="" alt="">
                    </div>
                    
                    <div class="yedp-info-box">
                        <span class="yedp-info-title">Welcome</span>
                        <span class="yedp-info-text">Hover over any option to see details and a preview image.</span>
                    </div>
                    
                    <div class="yedp-label">Final Prompt String</div>
                    <textarea class="yedp-output positive-output"></textarea>
                    
                    <div class="yedp-actions">
                        <button class="yedp-btn-action random-btn">🎲 Randomize</button>
                        <button class="yedp-btn-action reset-btn" style="background: #333; border-color: #666; margin-left: 5px;">↺ Reset</button>
                    </div>
                </div>
            </div>
        `;

        const subjInput = container.querySelector(".subject-input");
        const negInput = container.querySelector(".negative-input");
        const modeSelect = container.querySelector(".mode-select");
        const randBtn = container.querySelector(".random-btn");
        const resetBtn = container.querySelector(".reset-btn");
        const posOut = container.querySelector(".positive-output");

        subjInput.oninput = (e) => { node.state.subject = e.target.value; updateOutputs(); };
        negInput.oninput = (e) => { node.state.negative = e.target.value; updateOutputs(); };
        modeSelect.onchange = (e) => { node.state.mode = e.target.value; updateOutputs(); };
        posOut.oninput = (e) => { if(node.widgets && node.widgets[1]) node.widgets[1].value = e.target.value; };
        
        randBtn.onclick = () => {
            node.state.camera = categories.camera.options[Math.floor(Math.random()*categories.camera.options.length)].id;
            node.state.lighting = categories.lighting.options[Math.floor(Math.random()*categories.lighting.options.length)].id;
            node.state.palette = categories.palette.options[Math.floor(Math.random()*categories.palette.options.length)].id;
            node.state.artist = categories.artist.options[Math.floor(Math.random()*categories.artist.options.length)].id;
            node.state.style = [categories.style.options[Math.floor(Math.random()*categories.style.options.length)].id];
            node.state.dof = Math.floor(Math.random()*categories.dof.options.length);
            renderControls(); updateOutputs(); updatePreview('camera', node.state.camera);
        };

        resetBtn.onclick = () => {
            node.state.camera = ""; node.state.framing = ""; node.state.angle = "";
            node.state.focal = ""; node.state.lighting = ""; node.state.palette = "";
            node.state.artist = ""; node.state.style = []; node.state.texture = [];
            node.state.ratio = "16-9"; node.state.dof = 2;
            renderControls(); updateOutputs(); updatePreview('camera', 'arri'); 
        };

        modeSelect.value = node.state.mode;
        renderControls();
        updateOutputs();
        updatePreview('camera', node.state.camera || 'arri');
    };

    return { container, buildUI };
}


// 2. LOADER UI
function createLoaderUI(node) {
    node.bgcolor = "#222"; 
    
    if (node.widgets) {
        for (let w of node.widgets) {
            w.type = "hidden"; 
            w.computeSize = () => [0, -4]; 
        }
    }

    // Loader uses a simpler state tracking the currently selected item
    node.defaultState = {
        selectedCategory: null,
        selectedId: null
    };
    node.state = Object.assign({}, node.defaultState);

    const container = document.createElement("div");
    container.className = "yedp-container";
    container.innerHTML = `${style}<div class="yedp-layout" style="color:#666; justify-content:center; align-items:center;">Loading Reference Loader...</div>`;

    const updatePreview = (catKey, id) => {
        updatePreviewLogic(container, catKey, id, "loader", node);
    };

    const renderControls = () => {
        const controlsArea = container.querySelector(".dynamic-controls");
        if(!controlsArea) return; 
        controlsArea.innerHTML = "";
        
        Object.keys(categories).forEach(key => {
            // SKIP RATIO FOR LOADER
            if (key === 'ratio') return;
            
            const cat = categories[key];
            const label = document.createElement("div");
            label.className = "yedp-label";
            label.innerText = cat.title;
            controlsArea.appendChild(label);
            const wrapper = document.createElement("div");
            
            // For Loader, simplified rendering: List style or Grid for all, but enforce Single Select
            if (cat.type === 'slider') {
                // Sliders don't make much sense for "loading a specific image" unless we treat the slider positions as distinct images
                // Let's render them as buttons for the loader to make "one at a time" obvious
                wrapper.style.display = "flex"; wrapper.style.flexDirection = "column"; wrapper.style.gap = "4px";
                cat.options.forEach((opt, idx) => {
                      // Handle slider options which are array indices
                      const optId = idx;
                      const optLabel = opt.label;
                      const btn = document.createElement("div");
                      // Check if this specific slider value is the globally selected item
                      const isActive = (node.state.selectedCategory === key && node.state.selectedId === optId);
                      
                      btn.className = `yedp-btn ${isActive ? 'active' : ''}`;
                      btn.innerHTML = `<span>${optLabel}</span> ${isActive ? '●' : ''}`;
                      
                      btn.onmouseenter = () => updatePreview(key, optId);
                      btn.onclick = () => {
                          // Toggle off if clicking same
                          if (isActive) {
                             node.state.selectedCategory = null;
                             node.state.selectedId = null;
                             if(node.widgets[0]) node.widgets[0].value = "";
                          } else {
                             node.state.selectedCategory = key;
                             node.state.selectedId = optId;
                             // !!! MODIFIED: Update the widget output only here on CLICK
                             if(node.widgets[0]) node.widgets[0].value = `${key}_${opt.id}`;
                          }
                          renderControls();
                          // If selected, show preview. If deselected, maybe clear?
                          if (node.state.selectedCategory) {
                             updatePreview(node.state.selectedCategory, node.state.selectedId);
                          }
                      };
                      wrapper.appendChild(btn);
                });

            } else if (cat.type === 'ratio' || cat.type === 'multi') {
                wrapper.className = "yedp-grid";
                cat.options.forEach(opt => {
                    const btn = document.createElement("div");
                    // Global Single Select Logic
                    const isActive = (node.state.selectedCategory === key && node.state.selectedId === opt.id);
                        
                    btn.className = `yedp-grid-item ${isActive ? 'active' : ''}`;
                    btn.innerText = opt.label;
                    btn.onclick = () => {
                        if (isActive) {
                             node.state.selectedCategory = null;
                             node.state.selectedId = null;
                             if(node.widgets[0]) node.widgets[0].value = "";
                        } else {
                             node.state.selectedCategory = key;
                             node.state.selectedId = opt.id;
                             // !!! MODIFIED: Update the widget output only here on CLICK
                             if(node.widgets[0]) node.widgets[0].value = `${key}_${opt.id}`;
                        }
                        renderControls(); 
                        if (node.state.selectedCategory) updatePreview(key, opt.id);
                    };
                    btn.onmouseenter = () => updatePreview(key, opt.id);
                    wrapper.appendChild(btn);
                });
            } else {
                wrapper.style.display = "flex"; wrapper.style.flexDirection = "column"; wrapper.style.gap = "4px";
                cat.options.forEach(opt => {
                    const btn = document.createElement("div");
                    const isActive = (node.state.selectedCategory === key && node.state.selectedId === opt.id);

                    btn.className = `yedp-btn ${isActive ? 'active' : ''}`;
                    btn.innerHTML = `<span>${opt.label}</span> ${isActive ? '●' : ''}`;
                    btn.onmouseenter = () => updatePreview(key, opt.id);
                    btn.onclick = () => {
                        if (isActive) {
                             node.state.selectedCategory = null;
                             node.state.selectedId = null;
                             if(node.widgets[0]) node.widgets[0].value = "";
                        } else {
                             node.state.selectedCategory = key;
                             node.state.selectedId = opt.id;
                             // !!! MODIFIED: Update the widget output only here on CLICK
                             if(node.widgets[0]) node.widgets[0].value = `${key}_${opt.id}`;
                        }
                        renderControls();
                        if (node.state.selectedCategory) updatePreview(key, opt.id);
                    };
                    wrapper.appendChild(btn);
                });
            }
            controlsArea.appendChild(wrapper);
        });
    };

    const buildUI = () => {
        container.innerHTML = `
            ${style}
            <div class="yedp-layout">
                <div class="yedp-sidebar">
                    <div style="padding:10px; color:#888; font-size:11px; margin-bottom:10px;">
                        Select <strong>one</strong> reference image to load.
                    </div>
                    <div class="dynamic-controls"></div>
                </div>
                
                <div class="yedp-main">
                    <div class="yedp-label">Selected Reference</div>
                    <div class="yedp-preview-box">
                        <img class="yedp-preview-img" src="" alt="">
                    </div>
                    
                    <div class="yedp-info-box">
                        <span class="yedp-info-title">Welcome</span>
                        <span class="yedp-info-text">Hover to preview. Click to select (Single Selection).</span>
                    </div>
                    
                    <div class="yedp-actions" style="margin-top:auto">
                         <button class="yedp-btn-action reset-btn" style="background: #333; border-color: #666;">↺ Deselect All</button>
                    </div>
                </div>
            </div>
        `;

        const resetBtn = container.querySelector(".reset-btn");
        resetBtn.onclick = () => {
            node.state.selectedCategory = null;
            node.state.selectedId = null;
            if(node.widgets[0]) node.widgets[0].value = ""; // Clear output on reset
            renderControls(); 
            // Maybe clear preview or show placeholder?
        };

        renderControls();
        if (node.state.selectedCategory) {
            updatePreview(node.state.selectedCategory, node.state.selectedId);
        }
    };

    return { container, buildUI };
}


// --- REGISTER EXTENSION ---
app.registerExtension({
    name: "Yedp.CinematicPromptCN",
    async beforeRegisterNodeDef(nodeType, nodeData, app) {
        
        // 1. PROMPT BUILDER NODE
        if (nodeData.name === "CinematicPromptNodeCN") {
            const onNodeCreated = nodeType.prototype.onNodeCreated;
            nodeType.prototype.onNodeCreated = function () {
                const r = onNodeCreated ? onNodeCreated.apply(this, arguments) : undefined;
                const ui = createPromptBuilderUI(this);
                this.addDOMWidget("cinematic_ui", "html", ui.container, {
                    getValue: () => this.state,
                    setValue: (v) => { if (v) this.state = Object.assign({}, this.defaultState, v); setTimeout(ui.buildUI, 50); }
                });
                requestAnimationFrame(() => { this.setSize([750, 850]); ui.buildUI(); });
                return r;
            };
        }
        
        // 2. REFERENCE LOADER NODE
        if (nodeData.name === "CinematicLoaderNodeCN") {
            const onNodeCreated = nodeType.prototype.onNodeCreated;
            nodeType.prototype.onNodeCreated = function () {
                const r = onNodeCreated ? onNodeCreated.apply(this, arguments) : undefined;
                const ui = createLoaderUI(this);
                this.addDOMWidget("cinematic_loader_ui", "html", ui.container, {
                    getValue: () => this.state,
                    setValue: (v) => { if (v) this.state = Object.assign({}, this.defaultState, v); setTimeout(ui.buildUI, 50); }
                });
                requestAnimationFrame(() => { this.setSize([750, 850]); ui.buildUI(); });
                return r;
            };
        }
    }
});
