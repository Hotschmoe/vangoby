# Vangoby NFT Owners' Powder Calculator

A high-performance web application to analyze NFT collection holders' liquid net worth over time. Track how much ETH ("powder") unique NFT holders have accumulated across three time points: now, 6 months ago, and 1 year ago.

## Features

- **Historical Analysis**: Analyze NFT holder wealth at current time, 6 months ago, and 1 year ago
- **Unique Holder Detection**: Identifies unique owners across all tokens in a collection
- **ETH Balance Calculation**: Calculates total and average ETH holdings for all unique holders
- **Trend Visualization**: Interactive Plotly charts showing average ETH per owner over time
- **High Performance**: Optimized batch RPC calls and parallel processing for fast results
- **Archive Node Ready**: Works with local Erigon or other archive-enabled Ethereum nodes

## Tech Stack

- **Frontend**: Single HTML file with HTMX for dynamic updates
- **Backend**: Python Flask with Web3.py for Ethereum interaction
- **Database**: None - real-time blockchain data fetching
- **Deployment**: Docker with docker-compose for easy home server deployment

## Quick Start with Docker

1. **Clone and setup**:
```bash
git clone <your-repo>
cd vangoby
```

2. **Configure your Ethereum node**:
```bash
cp .env.example .env
# Edit .env and set NODE_URL to your local Erigon node
```

3. **Run with docker-compose**:
```bash
docker compose up -d
```

4. **Access the application**:
   - Open http://localhost:5000 in your browser
   - Enter an NFT collection contract address (e.g., `0xBC4CA0EdA7647A8aB7C2061c2E118A18a936f13D` for BAYC)
   - Click "Calculate Owners' Powder"

## Local Development Setup

1. **Install Python dependencies**:
```bash
cd src
pip install -r requirements.txt
```

2. **Configure Ethereum node**:
   - Edit `src/app.py` and update `NODE_URL = 'http://192.168.10.8:8545'`
   - Ensure your Ethereum node is an archive node or has sufficient historical state

3. **Run locally**:
```bash
cd src
python app.py
```

## Configuration

Key settings in `src/app.py`:
- `NODE_URL`: Your Ethereum RPC endpoint (requires archive node for historical data)
- `MAX_TOKENS_TO_CHECK`: Maximum tokens to analyze per time point (default: 10000)
- `REQUEST_TIMEOUT`: RPC request timeout in seconds (default: 240)
- `AVG_BLOCK_TIME_SECONDS`: Used for historical block calculations (default: 12)

Docker environment variables:
- `NODE_URL`: Override RPC endpoint
- `MAX_TOKENS_TO_CHECK`: Override token limit
- `REQUEST_TIMEOUT`: Override timeout
- `AVG_BLOCK_TIME_SECONDS`: Override block time

## Performance Features

- **Batch RPC Calls**: Groups multiple `ownerOf` and balance requests into single RPC calls
- **Parallel Processing**: Fetches data for all three time points simultaneously
- **Connection Pooling**: Optimized HTTP session management for sustained performance
- **Smart Caching**: Reduces redundant blockchain queries

## Performance Testing

The repository includes a performance benchmarking tool to measure analysis speed and track optimization improvements.

### Running Performance Tests

1. **Start the application** (Docker or local):
```bash
# With Docker
docker compose up -d

# Or locally
cd src && python app.py
```

2. **Run performance tests**:
```bash
cd src
python performance_metrics.py
```

3. **View results**:
   - Real-time output appears in console
   - Detailed logs saved to `src/performance.log`
   - Shows average, min, and max response times across multiple runs

### Test Configuration

Edit `src/performance_metrics.py` to customize:
- `TEST_COLLECTION_ADDRESS`: NFT collection to test (default: MFer collection)
- `NUM_RUNS`: Number of test iterations (default: 3)
- `APP_URL`: Target URL if running on different port/host

### Performance Baseline

Typical performance on home server with local Erigon node:
- **Small collections** (100-1000 tokens): 10-30 seconds
- **Medium collections** (1000-5000 tokens): 30-90 seconds  
- **Large collections** (5000-10000 tokens): 90-300 seconds

Performance scales with:
- Collection size (number of tokens)
- RPC latency to Ethereum node
- Historical data availability
- Server CPU/memory resources

## Project Structure

```
vangoby/
├── src/                      # Main application code
│   ├── app.py               # Flask backend with blockchain logic
│   ├── index.html           # HTMX frontend
│   ├── performance_metrics.py # Performance benchmarking tool
│   └── requirements.txt     # Python dependencies
├── archive/                  # Archived experimental implementations
├── mev-bots-separate/       # MEV bot experiments (separate project)
├── Dockerfile               # Container definition
├── docker-compose.yml       # Docker orchestration
├── .env.example            # Environment variables template
└── README.md               # This file
```
