# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Vangoby is an NFT collection analysis platform with multiple implementations exploring different tech stacks. The main application compares NFT collections to analyze holder liquid net worth, with experimental variants in Go (htmx-go), Python (htmx-py), and MEV bot components.

## Core Architecture

### Main Application (Bun + Preact)
- **Entry Point**: `index.ts` - Main server that serves static files and proxies API requests
- **Backend**: `backend/server.ts` - API server handling NFT data fetching using ethers.js
- **Frontend**: `frontend/src/` - Preact + TypeScript UI with component-based architecture
- **Build System**: Bun's built-in bundler with automatic frontend compilation

### Data Flow
1. Frontend sends requests to `/api/nft-data` with contract addresses
2. Backend queries Ethereum mainnet via Alchemy demo RPC
3. Currently returns mock data; real implementation would fetch holder lists and ETH balances
4. Results displayed in side-by-side comparison cards

### Alternative Implementations
- **htmx-go/**: Go backend with HTMX frontend, uses Go-Ethereum client
- **htmx-py/**: Flask backend with web3.py, includes performance testing
- **mev-bots/**: Experimental MEV bot components

## Development Commands

```bash
# Development server with auto-reload
bun run dev

# Production server
bun run start

# Build frontend only
bun run build
```

## Key Technical Details

- **Port Configuration**: Frontend on 3001, backend on 3002
- **Ethereum Integration**: Uses ethers.js with Alchemy RPC (demo key)
- **State Management**: Preact hooks for component state
- **Build Output**: Frontend builds to `./public/` directory
- **TypeScript**: Configured for ESNext with strict mode

## Project Structure Context

The repository contains multiple proof-of-concept implementations:
- Main Bun/Preact app in root directory
- Go variant using Gorilla mux and go-ethereum
- Python variant using Flask and web3.py
- Shared goal of analyzing NFT holder wealth distribution

## Testing Notes

No test framework is currently configured. The htmx-py implementation includes performance testing via `performance_metrics.py`.

## Known Limitations

- Backend currently uses mock data instead of real blockchain queries
- Ethereum node connection requires archive node for historical data
- Rate limiting and caching not yet implemented