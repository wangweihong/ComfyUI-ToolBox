import { defineConfig } from 'vite';
import { resolve } from 'node:path';
export default defineConfig({
  root: 'frontend/media_library', base: './',
  build: {outDir: '../../nodes/media_library/web/dist', emptyOutDir: true,
    rollupOptions: {input: resolve(import.meta.dirname, 'frontend/media_library/gallery.html')}},
});
