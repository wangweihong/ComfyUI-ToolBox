import {build} from 'esbuild';
import {readFile, writeFile} from 'node:fs/promises';

await build({
    entryPoints: ['frontend/skill_markdown.mjs'],
    outfile: 'web/js/skill_markdown.mjs',
    bundle: true, format: 'esm', minify: true, legalComments: 'eof',
});
const notices = await Promise.all(['marked', 'dompurify'].map(async name => {
    const manifest = JSON.parse(await readFile(`node_modules/${name}/package.json`, 'utf8'));
    return `${name} ${manifest.version}\n${await readFile(`node_modules/${name}/LICENSE`, 'utf8')}`;
}));
await writeFile('web/js/skill_markdown.LICENSE.txt', notices.join('\n\n'));
