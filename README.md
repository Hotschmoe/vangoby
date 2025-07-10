# Vangoby

A web application to analyze and compare NFT collection holders' liquid net worth. Get insights into unique holders, total ETH holdings, and ETH/holder ratios for any two NFT collections.

## Features

- Compare two NFT collections side by side
- View unique holder counts
- Calculate total ETH holdings
- Analyze ETH/holder ratio metrics
- Real-time Ethereum blockchain data

## Tech Stack

### Frontend
- Preact + TypeScript
- Bun's built-in bundler
- Modern, responsive UI

### Backend
- Bun runtime
- Ethers.js for Ethereum interaction
- Public RPC initially (Alchemy)
- Local Ethereum node support (planned)

## Setup

1. Install dependencies:
```bash
# Install Bun
curl -fsSL https://bun.sh/install | bash

# Install project dependencies
bun install
```

2. Start the development server:
```bash
# Run with auto-reload
bun run dev

# Or for production
bun run start
```

3. Visit `http://localhost:3000` in your browser

## Development

The project is structured into two main parts:

- `/frontend` - Preact + TypeScript UI
- `/backend` - Bun server with Ethereum integration

See `TODO.md` for detailed development tasks and progress tracking.

## Project Structure

```
vangoby/
├── frontend/                 # Frontend code
│   ├── public/               # Static files
│   │   └── index.html        # Main HTML template
│   ├── src/                  # Source code
│   │   ├── App.tsx           # Main app component
│   │   └── index.tsx         # Entry point
│   └── tsconfig.json         # TypeScript config for frontend
├── backend/                  # Backend code
│   └── server.ts             # API server
├── public/                   # Built frontend files (generated)
├── index.ts                  # Main server entry point
├── package.json              # Project dependencies
└── tsconfig.json             # TypeScript config
```

## Available Scripts

- `bun run dev` - Start development server with auto-reload
- `bun run start` - Start production server
- `bun run build` - Build frontend for production
