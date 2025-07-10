import { server as backendServer } from './backend/server';
import { file, serve } from 'bun';
import fs from 'fs';
import path from 'path';

// Define the directory for static files
const PUBLIC_DIR = path.join(import.meta.dir, 'public');

// Create public directory if it doesn't exist
if (!fs.existsSync(PUBLIC_DIR)) {
  fs.mkdirSync(PUBLIC_DIR, { recursive: true });
}

// Main server that handles both static files and proxies API requests
const server = Bun.serve({
  port: 3001,
  async fetch(req) {
    const url = new URL(req.url);
    
    // Handle API requests by forwarding to backend
    if (url.pathname.startsWith('/api/')) {
      return backendServer.fetch(req);
    }
    
    // Serve static files
    let filePath = url.pathname;
    if (filePath === '/') filePath = '/index.html';
    
    const fullPath = path.join(PUBLIC_DIR, filePath);
    
    // Check if the file exists in the public directory
    try {
      if (fs.existsSync(fullPath)) {
        return new Response(Bun.file(fullPath));
      }
    } catch (err) {
      console.error('Error accessing static file:', err);
    }
    
    // If no file found, send a 404
    return new Response('File not found', { status: 404 });
  },
});

console.log(`Frontend server running at http://localhost:${server.port}`);

// Build function to compile frontend
export async function buildFrontend() {
  console.log('Building frontend...');
  
  try {
    const result = await Bun.build({
      entrypoints: ['./frontend/src/index.tsx'],
      outdir: './public',
      minify: true,
    });
    
    // Copy index.html to public
    fs.copyFileSync(
      path.join(import.meta.dir, 'frontend/public/index.html'),
      path.join(PUBLIC_DIR, 'index.html')
    );
    
    console.log('Frontend built successfully');
    return result.success;
  } catch (error) {
    console.error('Frontend build failed:', error);
    return false;
  }
}

// Run build on startup (comment out during development to speed up restarts)
await buildFrontend();
