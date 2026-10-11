import schema from './stocking_effect_schema.json?v=20261011-material6' with {type:'json'};
import {PATTERN_STYLES} from './stocking_style_registry.mjs?v=20261011-material6';
export const SCHEMA=schema;
export const LAYER_TYPES=Object.keys(schema.types).filter(k=>schema.types[k].layer);
export function fields(raw,specs,partial=false,strict=true) {
    if(!raw||typeof raw!=='object'||Array.isArray(raw))throw new Error('配置必须为对象');
    if(strict&&Object.keys(raw).some(k=>!(k in specs)))throw new Error('不支持此配置参数');
    const out={};
    for(const [k,s] of Object.entries(specs)) {
        if(partial&&!(k in raw))continue;
        let v=Object.hasOwn(raw,k)?raw[k]:s.default;
        if(s.type==='boolean'&&typeof v!=='boolean')throw new Error(`${k} 必须为布尔值`);
        if(s.type==='number'){if(typeof v!=='number'||!Number.isFinite(v))throw new Error(`${k} 必须为有限数值`);v=Math.max(s.min,Math.min(s.max,v));}
        if(s.type==='enum'&&!s.options.includes(v))throw new Error(`未知 ${k}`);
        if(s.type==='color'){if(typeof v!=='string'||!/^#[0-9a-f]{6}$/i.test(v))throw new Error('颜色必须为 #RRGGBB');v=v.toLowerCase();}
        if(s.type==='string'&&(typeof v!=='string'||v.length>(s.maxLength??4096)||s.ascii&&/[^\x20-\x7e]/.test(v)))throw new Error('文字最多 128 个可打印 ASCII 字符');
        out[k]=v;
    }
    return out;
}
export function cleanLayer(layer) {
    if(!layer||!LAYER_TYPES.includes(layer.type)||Object.keys(layer).some(k=>!['id','type','params'].includes(k)))throw new Error('不支持此图层类型');
    if(typeof layer.id!=='string'||!layer.id||layer.id.length>128)throw new Error('图层 id 无效');
    return {id:layer.id,type:layer.type,params:fields(layer.params??{},schema.groups[layer.type])};
}
export function cleanV2(raw) {
    if(raw.version!==2||Object.keys(raw).some(k=>!['version','layers','damage','sampling'].includes(k)))throw new Error('不支持此效果配置版本或参数');
    if(!Array.isArray(raw.layers??[])||(raw.layers??[]).length>schema.max_layers)throw new Error('每套材质最多 16 个图层');
    const layers=(raw.layers??[]).map(cleanLayer);
    if(new Set(layers.map(x=>x.id)).size!==layers.length)throw new Error('图层 id 必须唯一');
    if(!['field','v1'].includes(raw.sampling??'field'))throw new Error('未知采样版本');
    return {version:2,layers,damage:fields(raw.damage??{},schema.groups.damage),sampling:raw.sampling??'field'};
}
export function cleanEffects(raw='{}') {
    if(typeof raw==='string'&&new TextEncoder().encode(raw).length>65536)throw new Error('效果配置超过 64 KiB');
    const obj=typeof raw==='string'?JSON.parse(raw||'{}'):raw;
    if(!obj||typeof obj!=='object'||Array.isArray(obj))throw new Error('效果配置必须为对象');
    if((Object.hasOwn(obj,'version')?obj.version:1)!==1)return cleanV2(obj);
    const result={version:1};
    for(const kind of ['pattern','text','damage']) {
        const specs=Object.fromEntries(Object.entries(schema.legacy_defaults[kind]).map(([k,v])=>[k,{...schema.groups[kind][k],default:v}]));
        result[kind]=fields(obj[kind]??{},specs,false,false);
    }
    return result;
}
export function normalizeEffects(style,raw='{}') {
    const cfg=cleanEffects(raw),base=PATTERN_STYLES.has(style)?'knit':style==='p_oily'?'oily':style;
    if(cfg.version===2) {
        if(PATTERN_STYLES.has(style))cfg.layers.unshift(cleanLayer({id:'legacy-style',type:'pattern',params:{pattern:style}}));
        return {style:base,effects:cleanV2(cfg)};
    }
    const layers=[];
    if(PATTERN_STYLES.has(style))layers.push(cleanLayer({id:'legacy-pattern',type:'pattern',params:{...cfg.pattern,pattern:style,enabled:true}}));
    layers.push(cleanLayer({id:'legacy-text',type:'text',params:{...cfg.text,mode:cfg.pattern.mode}}));
    return {style:base,effects:{version:2,layers,damage:cfg.damage,sampling:'v1'}};
}
export function cleanOverride(raw) {
    if(!raw||Object.keys(raw).some(k=>!['params','layers','damage'].includes(k)))throw new Error('部位材质包含不支持的参数');
    const out={params:fields(raw.params??{},schema.appearance,true)};
    if('layers' in raw)out.layers=cleanV2({version:2,layers:raw.layers}).layers;
    if('damage' in raw)out.damage=fields(raw.damage,schema.groups.damage,true);
    return out;
}
