# NFT Owners' Powder Calculator - Go Version

A web application that calculates the total and average amount of ETH ("powder") held by NFT collection owners at different points in time.

## Features

- Analyzes NFT collection ownership at three time points: current, 6 months ago, and 1 year ago
- Calculates the total ETH balance held by all owners at each time point
- Generates a trend chart showing how average ETH per owner has changed over time
- Uses HTMX for responsive, partial page updates without full page reloads

## Requirements

- Go 1.18 or later (for local development)
- Docker and Docker Compose (for containerized deployment)
- Access to an Ethereum RPC node (local or remote)
- Internet connection (for loading external resources like HTMX and Plotly)

## Standard Installation (Local Development)

1. Clone the repository:
   ```
   git clone https://github.com/yourusername/nft-owners-powder.git
   cd nft-owners-powder/htmx-go
   ```

2. Install Go dependencies:
   ```
   go mod init htmx-go
   go get github.com/ethereum/go-ethereum
   go get github.com/gorilla/mux
   ```

3. Configure the Ethereum node URL:
   - Open `backend.go` and modify the `NodeURL` constant to point to your Ethereum node
   - Default configuration uses `http://192.168.10.8:8545`

4. Create a `templates` directory and copy the index.html file into it:
   ```
   mkdir -p templates
   cp index.html templates/
   ```

5. Create a `static` directory for any static assets:
   ```
   mkdir -p static
   ```

## Docker Installation

1. Clone the repository:
   ```
   git clone https://github.com/yourusername/nft-owners-powder.git
   cd nft-owners-powder/htmx-go
   ```

2. Create a `templates` directory and copy the index.html file into it:
   ```
   mkdir -p templates
   cp index.html templates/
   ```

3. Create a `static` directory for any static assets:
   ```
   mkdir -p static
   ```

4. Modify the Ethereum node URL in docker-compose.yml:
   - Uncomment and update the NODE_URL environment variable in the docker-compose.yml file
   - For connecting to a node on your host machine, use `http://host.docker.internal:8545`

5. Build and run with Docker Compose:
   ```
   docker-compose up -d
   ```

6. The application will be available at http://localhost:5000

## Usage (Local Development)

1. Build and run the application:
   ```
   go build -o powder-app backend.go
   ./powder-app
   ```

2. The server will start on port 5000 by default. Open your browser and navigate to:
   ```
   http://localhost:5000
   ```

3. Enter an NFT collection address (ERC-721 contract) and click "Calculate Owners' Powder"

## API Endpoints

- `GET /` - Serves the main application page
- `POST /get-owners-powder` - Calculates owner powder for a specific NFT collection
- `GET /sse-owners-powder` - Server-Sent Events endpoint for progressive loading
- `GET /health` - Health check endpoint

## Configuration

You can configure the following constants in `backend.go`:

- `NodeURL` - URL of the Ethereum RPC node
- `RequestTimeout` - Timeout for RPC requests in seconds
- `MaxTokensToCheck` - Maximum number of tokens to check per collection
- `AvgBlockTimeSeconds` - Average Ethereum block time used for historical block calculations

## Docker Environment Variables

When running with Docker, you can configure the application using these environment variables:

- `PORT` - The port to listen on (default: 5000)
- `NODE_URL` - The Ethereum node URL (uncomment in docker-compose.yml)

## Missing Dependencies

If you encounter compile errors, you may need to add the standard library "strings" package which is used but not explicitly imported. Add it to the import section of backend.go:

```go
import (
    // existing imports...
    "strings"
)
```

## Static Files

Place any static files (CSS, JavaScript, images) in a `static` directory, which will be served under the `/static/` path.

## Building for Production

For production deployment, build with optimizations:

```bash
go build -ldflags="-s -w" -o powder-app backend.go
```

Or use the Docker deployment method for a containerized production environment.

## License

[MIT License](LICENSE)
