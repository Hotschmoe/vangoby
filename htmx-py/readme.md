# HTMX + Python Backend for NFT Owner Analysis (PoC)

This project is a Proof-of-Concept (PoC) demonstrating how to build a simple web application using:

*   **Frontend:** HTMX for dynamic updates without complex JavaScript.
*   **Backend:** Flask (Python) for handling logic and serving data.
*   **Data Source:** An Ethereum node (specifically Erigon is assumed for the default URL) for fetching blockchain data via Web3.py.

## Features

*   **Input:** Takes an NFT collection contract address.
*   **Output:**
    *   Finds unique owners of the NFT collection.
    *   Calculates the total ETH balance ("Owners' Powder") held by these unique owners.
    *   Performs this analysis for three time points: **Now**, approximately **6 months ago**, and approximately **1 year ago**.
    *   Displays the results in a summary table.
    *   Generates a Plotly line graph visualizing the trend of **Average ETH Balance per Unique Owner** over the three time points.

## Current Limitations & Performance Considerations

*   **Archive Node Required:** Fetching historical blockchain state (owners and balances at past blocks) requires the connected Ethereum node to be an **archive node** or have sufficient historical state available. Standard full/pruned nodes will likely fail on historical queries.
*   **Minimal ABI:** The current backend uses a minimal ERC721 ABI containing only `totalSupply` and `ownerOf`. This might not be sufficient for all NFT contracts, especially if different function signatures are used or if future optimizations require other functions (like those related to events). Broader ABI compatibility might be needed in the future.
*   **Inefficient Owner Fetching (`ownerOf` loop):** The current implementation finds owners by iterating through token IDs (from 0 up to `MAX_TOKENS_TO_CHECK` or `totalSupply`) and calling the `ownerOf` function for each. This is **highly inefficient** for several reasons:
    *   It makes one RPC call per token ID checked.
    *   It doesn't work well for contracts with non-sequential token IDs or very large gaps.
    *   It's extremely slow for collections with thousands of tokens.
*   **`MAX_TOKENS_TO_CHECK` Limit:** To prevent extremely long request times with the current inefficient method, the `app.py` script includes a `MAX_TOKENS_TO_CHECK` setting (default: 100). This limits the number of token IDs checked *per time point*. For collections larger than this, the results will be **incomplete** and likely inaccurate.

## Performance Testing & Optimization Goal

Due to the limitations mentioned above, especially the `ownerOf` loop, the application is currently very slow for large collections.

To address this, we have implemented a basic performance testing script:

*   **Script:** `performance_metrics.py`
*   **Function:** Sends requests to the running Flask application for a predefined test collection address (currently set to MFERs: `0x79FCDEF22feeD20eDDacbB2587640e45491b757f`).
*   **Logging:** Measures the total request time for each run and logs it along with timestamps to `performance.log`.

This script allows us to establish baseline performance metrics and track improvements as we modify the backend logic in `app.py`.

**The primary optimization goal is to refactor the data fetching mechanism to efficiently support analyzing collections with large numbers of tokens (e.g., 10,000+) without unreasonable delays or timeouts.** This will likely involve switching from `ownerOf` iteration to scanning `Transfer` events emitted by the NFT contract, which is a more standard and scalable approach. 

## Running the Project

1.  **Clone/Setup:** Get the project files.
2.  **Install Dependencies:**
    ```bash
    pip install -r requirements.txt
    ```
3.  **Run Backend:** Ensure your Ethereum (archive) node is running and accessible, then:
    ```bash
    python app.py
    ```
    *(Note: The default node URL `http://192.168.10.8:8545` is hardcoded in `app.py`. Adjust if necessary.)*
4.  **Access Frontend:** Open your browser to `http://localhost:5000` (or the appropriate IP/port).
5.  **Run Performance Test (Optional):** While the backend is running, open another terminal in the project directory and run:
    ```bash
    python performance_metrics.py
    ```
    *(Check `performance.log` for results.)*