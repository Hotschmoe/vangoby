Below is a detailed TODO list for your project, split into Frontend and Backend sections, designed for an init.md file. The project uses Bun as the runtime for both the backend API and serving the frontend, with Preact + TypeScript for the frontend. The goal is a one-page website where users enter two NFT contract addresses and see a snapshot of unique holders, total ETH, and ETH/holder ratio. I've kept it simple and actionable, assuming a local Ethereum node will eventually replace a public RPC.
init.md - Project TODO List
Project Overview
Goal: Build a one-page website to lookup NFT contract data (unique holders, total ETH, ETH/holder ratio) at the time of submission.
Tech Stack:
Backend: Bun, Ethers.js (for Ethereum queries), public RPC initially (e.g., Alchemy), later a local ETH node.
Frontend: Preact + TypeScript, bundled with Bun's built-in bundler, served by Bun.
Serving: Bun handles both API and static frontend files.
Frontend TODO
1. Setup Project Structure
Create a frontend directory in the project root.
Initialize a package.json in frontend with bun init.
Install dependencies:
bun add preact preact-render-to-string.
bun add -D typescript @types/preact.
Create basic file structure:
frontend/src/App.tsx (main component).
frontend/src/index.tsx (entry point).
frontend/public/index.html (static template).
frontend/tsconfig.json (TypeScript config).
2. Configure TypeScript
Add a tsconfig.json in frontend:
json
{
  "compilerOptions": {
    "target": "ESNext",
    "module": "ESNext",
    "jsx": "react-jsx",
    "jsxImportSource": "preact",
    "strict": true,
    "esModuleInterop": true,
    "outDir": "../public"
  },
  "include": ["src"]
}
Ensure TypeScript recognizes Preact types.
3. Build the UI with Preact
In src/App.tsx, create a component with:
Two input fields for NFT contract addresses (e.g., contractX, contractY).
A "Submit" button.
A results section (initially empty) for displaying data.
Example structure:
tsx
import { h, FunctionalComponent } from 'preact';
import { useState } from 'preact/hooks';

const App: FunctionalComponent = () => {
  const [contractX, setContractX] = useState('');
  const [contractY, setContractY] = useState('');
  const [results, setResults] = useState(null);

  const handleSubmit = async () => {
    // TODO: Fetch data
  };

  return (
    <div>
      <input value={contractX} onInput={(e) => setContractX(e.target.value)} placeholder="Contract X" />
      <input value={contractY} onInput={(e) => setContractY(e.target.value)} placeholder="Contract Y" />
      <button onClick={handleSubmit}>Submit</button>
      {/* TODO: Display results */}
    </div>
  );
};

export default App;
Style minimally with inline CSS or a style.css file (e.g., flexbox for layout).
4. Implement API Fetching
In App.tsx, add logic to fetch data from the backend:
On "Submit" click, send a fetch request to /api/nft-data?contractX=${contractX}&contractY=${contractY}.
Handle loading state (e.g., show "Loading..." while fetching).
Update results state with the response JSON.
Example:
tsx
const handleSubmit = async () => {
  setResults(null); // Clear previous results
  const res = await fetch(`/api/nft-data?contractX=${contractX}&contractY=${contractY}`);
  const data = await res.json();
  setResults(data);
};
Add basic error handling (e.g., show "Error fetching data" if the request fails).
5. Display Results
In App.tsx, render the results when available:
Show two sections (e.g., cards or a table) for X and Y.
Display holders, totalEth, and ethPerHolder for each.
Example:
tsx
{results && (
  <div>
    <div>
      <h2>Collection X</h2>
      <p>Holders: {results.X.holders}</p>
      <p>Total ETH: {results.X.totalEth}</p>
      <p>ETH/Holder: {results.X.ethPerHolder}</p>
    </div>
    <div>
      <h2>Collection Y</h2>
      <p>Holders: {results.Y.holders}</p>
      <p>Total ETH: {results.Y.totalEth}</p>
      <p>ETH/Holder: {results.Y.ethPerHolder}</p>
    </div>
  </div>
)}
6. Bundle with Bun
Use Bun's built-in bundler to build the app:
```bash
# From the frontend directory
bun build ./src/index.tsx --outdir ../public --minify
```

Add a public/index.html file:
html
<!DOCTYPE html>
<html>
  <head>
    <title>NFT Lookup</title>
  </head>
  <body>
    <div id="root"></div>
    <script src="/index.js"></script>
  </body>
</html>
In src/index.tsx, render the app:
tsx
import { h, render } from 'preact';
import App from './App';

render(<App />, document.getElementById('root')!);
Test the build: bun build ./src/index.tsx --outdir ../public.
Backend TODO
1. Setup Project Structure
Create a backend directory in the project root (or use the root if combined with frontend).
Initialize a package.json with bun init.
Install dependencies:
bun add ethers.
Create a server.ts file as the entry point.
2. Configure Bun Server
In server.ts, set up a basic Bun server:
ts
Bun.serve({
  port: 3000,
  async fetch(req) {
    const url = new URL(req.url);
    if (url.pathname === '/api/nft-data') {
      // TODO: Handle API logic
      return new Response('TODO', { status: 200 });
    }
    // Serve static frontend files
    const filePath = url.pathname === '/' ? 'public/index.html' : `public${url.pathname}`;
    const file = Bun.file(filePath);
    return new Response(file);
  },
});
console.log('Server running on http://localhost:3000');
Ensure the public directory (from frontend build) is in the root.
3. Integrate Ethereum Queries with Ethers.js
In server.ts, configure Ethers.js with a public RPC (e.g., Alchemy):
ts
import { ethers } from 'ethers';
const provider = new ethers.JsonRpcProvider('https://eth-mainnet.alchemyapi.io/v2/YOUR_API_KEY');
Later, switch to a local node (e.g., http://localhost:8545) when set up.
4. Implement NFT Data Logic
In the /api/nft-data handler:
Extract contractX and contractY from query params:
ts
const contractX = url.searchParams.get('contractX');
const contractY = url.searchParams.get('contractY');
if (!contractX || !contractY) return new Response('Missing contract addresses', { status: 400 });
Create a function to fetch data for one contract:
ts
async function getNFTData(contractAddress: string) {
  const contract = new ethers.Contract(
    contractAddress,
    ['function ownerOf(uint256) view returns (address)'],
    provider
  );
  // TODO: Fetch holders (simplified, use logs or API for efficiency)
  const holders = new Set<string>();
  for (let tokenId = 1; tokenId <= 100; tokenId++) { // Limited for demo
    try {
      const owner = await contract.ownerOf(tokenId);
      holders.add(owner);
    } catch {}
  }
  // Fetch ETH balances
  let totalEth = 0n;
  for (const holder of holders) {
    const balance = await provider.getBalance(holder);
    totalEth += balance;
  }
  const ethPerHolder = holders.size > 0 ? Number(totalEth) / 1e18 / holders.size : 0;
  return {
    holders: holders.size,
    totalEth: Number(totalEth) / 1e18,
    ethPerHolder,
  };
}
Call it for both contracts and return JSON:
ts
const dataX = await getNFTData(contractX);
const dataY = await getNFTData(contractY);
return new Response(JSON.stringify({ X: dataX, Y: dataY }), {
  headers: { 'Content-Type': 'application/json' },
});
5. Optimize Holder Fetching
Replace the ownerOf loop with a more efficient method:
Use event logs (Transfer events) to get historical owners.
Or integrate an NFT API (e.g., Alchemy SDK) temporarily until the local node is ready.
Test with small collections first (e.g., 10-100 tokens).
6. Setup Local ETH Node (Later)
Install Geth: brew install go-ethereum (or equivalent).
Start syncing: geth --http.
Update provider in server.ts to http://localhost:8545.
General TODO
Create a root public directory for frontend output.
Run the frontend build: cd frontend && bun build ./src/index.tsx --outdir ../public.
Start the server: cd backend && bun run server.ts.
Test end-to-end: Visit http://localhost:3000, enter contract addresses, and verify results.
Notes
Frontend: Keep it lightweight; expand with historical data later.
Backend: The ownerOf loop is a placeholder; optimize with logs or an API for real use.
Scaling: Add a database (e.g., SQLite) later if lookups are slow or repetitive.
Let me know if you need help with any step!