import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

// Vite builds the React app into ./dist, which Express serves in server.js.
export default defineConfig({
  plugins: [react()],
  build: {
    outDir: 'dist'
  }
});
