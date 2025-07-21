# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Vangoby is a high-performance NFT holder wealth analysis tool. It analyzes how much ETH ("powder") unique holders of NFT collections have accumulated over time, comparing three time points: current, 6 months ago, and 1 year ago.

## Current Architecture

### Main Application (Python + HTMX)
- **Backend**: `src/app.py` - Flask server with Web3.py for blockchain interaction
- **Frontend**: `src/index.html` - Single HTML file with HTMX for dynamic updates
- **Dependencies**: `src/requirements.txt` - Flask, web3, plotly

### Data Flow
1. User submits NFT collection address via HTMX form
2. Flask backend calculates historical block numbers (6mo, 1yr ago)
3. Parallel processing fetches owner data at all three time points
4. Batch RPC calls optimize blockchain queries (`ownerOf`, `getBalance`)
5. Results returned as HTML with Plotly chart embedded

### Performance Optimizations
- **Batch RPC calls**: Groups multiple blockchain queries into single requests
- **Parallel execution**: Fetches all time points simultaneously using ThreadPoolExecutor
- **Connection pooling**: Optimized HTTP session management for RPC calls
- **Smart batching**: Processes tokens in configurable batch sizes (default: 25)

## Development Commands

### Docker (Recommended)
```bash
# Quick start
docker-compose up -d

# View logs
docker-compose logs -f

# Rebuild after changes
docker-compose up --build
```

### Local Development
```bash
# Install dependencies
cd src && pip install -r requirements.txt

# Run server
cd src && python app.py
```

## Key Configuration

**Environment Variables** (set in `.env` or docker-compose.yml):
- `NODE_URL`: Ethereum RPC endpoint (default: `http://192.168.10.8:8545`)
- `MAX_TOKENS_TO_CHECK`: Maximum tokens per time point (default: 10000)
- `REQUEST_TIMEOUT`: RPC timeout in seconds (default: 240)
- `AVG_BLOCK_TIME_SECONDS`: For historical block calculation (default: 12)

**Code Configuration** (in `src/app.py`):
- Lines 17-20: Core configuration constants
- Line 24-28: HTTP session pool settings
- Line 210: Batch size for RPC calls (25 tokens per batch)
- Line 135: Balance batch size (50 addresses per batch)

## Project Structure

```
src/
├── app.py           # Main Flask application with blockchain logic
├── index.html       # HTMX frontend with embedded CSS
└── requirements.txt # Python dependencies

archive/             # Archived experimental implementations
├── frontend/        # Old Preact frontend
├── backend/         # Old Bun backend  
├── htmx-go/         # Go implementation
└── ...

mev-bots-separate/   # MEV bot experiments (separate project)
```

## Technical Requirements

- **Archive Node Required**: Historical balance queries require archive-enabled Ethereum node
- **Memory**: Can handle large collections (10k+ tokens) with sufficient RAM
- **Network**: Stable connection to Ethereum RPC endpoint essential

## Performance Notes

- Collection analysis time scales with token count and RPC latency
- Batch sizes (25 tokens, 50 addresses) optimized for typical RPC limits
- Parallel processing significantly reduces total execution time
- Connection pooling prevents RPC connection exhaustion

## Deployment Context

Designed for home server deployment with local Erigon node. Docker setup includes health checks, logging, and restart policies suitable for production self-hosting.