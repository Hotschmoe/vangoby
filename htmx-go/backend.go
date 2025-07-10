package main

import (
	"context"
	"embed"
	"encoding/json"
	"fmt"
	"html/template"
	"log"
	"math/big"
	"net/http"
	"os"
	"strings"
	"sync"
	"time"

	"github.com/ethereum/go-ethereum"
	"github.com/ethereum/go-ethereum/accounts/abi"
	"github.com/ethereum/go-ethereum/common"
	"github.com/ethereum/go-ethereum/ethclient"
	"github.com/ethereum/go-ethereum/rpc"
	"github.com/gorilla/mux"
)

//go:embed templates/*.html
var templateFS embed.FS

// Default configuration values
const (
	DefaultNodeURL       = "http://192.168.10.8:8545"
	RequestTimeout       = 240 * time.Second
	MaxTokensToCheck     = 10000
	AvgBlockTimeSeconds  = 12
)

// Runtime configuration (can be overridden with environment variables)
var (
	NodeURL string
)

// Minimal ERC721 ABI for totalSupply and ownerOf
const minimalERC721ABI = `[
    {
        "constant": true,
        "inputs": [],
        "name": "totalSupply",
        "outputs": [{"name": "", "type": "uint256"}],
        "payable": false,
        "stateMutability": "view",
        "type": "function"
    },
    {
        "constant": true,
        "inputs": [{"name": "tokenId", "type": "uint256"}],
        "name": "ownerOf",
        "outputs": [{"name": "", "type": "address"}],
        "payable": false,
        "stateMutability": "view",
        "type": "function"
    }
]`

// BlockResult stores data for a single block analysis
type BlockResult struct {
	Owners          int       `json:"owners"`
	BalanceEth      string    `json:"balance_eth"`
	CheckedTokens   int       `json:"checked_tokens"`
	Errors          []string  `json:"errors"`
	OwnerOfDuration float64   `json:"ownerof_duration"`
	BalanceDuration float64   `json:"balance_duration"`
	Block           int64     `json:"block"`
	Success         bool      `json:"success"`
}

// TimePoint represents a labeled point in time
type TimePoint struct {
	Label  string      `json:"label"`
	Block  int64       `json:"block"`
	Data   BlockResult `json:"data"`
}

// Response is the final structure returned to the frontend
type Response struct {
	TimePoints      []TimePoint `json:"time_points"`
	ExecutionTime   float64     `json:"execution_time"`
	GraphHTML       string      `json:"graph_html"`
	Errors          []string    `json:"errors"`
	TotalFetchTime  float64     `json:"total_fetch_time"`
}

// Cache for frequently accessed data
var (
	dataCache     = make(map[string][]byte)
	cacheMutex    = &sync.RWMutex{}
	cacheLifetime = 10 * time.Minute
)

func init() {
	// Load configuration from environment variables
	nodeURL := os.Getenv("NODE_URL")
	if nodeURL != "" {
		NodeURL = nodeURL
		log.Printf("Using Ethereum node URL from environment: %s", NodeURL)
	} else {
		NodeURL = DefaultNodeURL
		log.Printf("Using default Ethereum node URL: %s", NodeURL)
	}
}

func main() {
	r := mux.NewRouter()

	// Routes
	r.HandleFunc("/", serveIndex)
	r.HandleFunc("/get-owners-powder", handleOwnersPowder).Methods("POST")
	r.HandleFunc("/sse-owners-powder", handleSSEOwnersPowder).Methods("GET")
	r.HandleFunc("/health", handleHealth).Methods("GET")

	// Serve static files
	r.PathPrefix("/static/").Handler(http.StripPrefix("/static/", http.FileServer(http.Dir("./static"))))

	// Start server
	port := os.Getenv("PORT")
	if port == "" {
		port = "5000"
	}

	log.Printf("Starting server on port %s", port)
	log.Fatal(http.ListenAndServe(":"+port, r))
}

func serveIndex(w http.ResponseWriter, r *http.Request) {
	tmpl, err := template.ParseFS(templateFS, "templates/index.html")
	if err != nil {
		http.Error(w, "Error loading template", http.StatusInternalServerError)
		log.Printf("Error loading template: %v", err)
		return
	}

	err = tmpl.Execute(w, nil)
	if err != nil {
		http.Error(w, "Error executing template", http.StatusInternalServerError)
		log.Printf("Error executing template: %v", err)
		return
	}
}

func handleHealth(w http.ResponseWriter, r *http.Request) {
	// Try connecting to the Ethereum node
	client, err := ethclient.Dial(NodeURL)
	if err != nil {
		http.Error(w, fmt.Sprintf("Failed to connect to Ethereum node: %v", err), http.StatusInternalServerError)
		return
	}
	defer client.Close()

	// Get current block number to verify connection
	blockNumber, err := client.BlockNumber(context.Background())
	if err != nil {
		http.Error(w, fmt.Sprintf("Failed to get block number: %v", err), http.StatusInternalServerError)
		return
	}

	w.Header().Set("Content-Type", "application/json")
	json.NewEncoder(w).Encode(map[string]interface{}{
		"status":       "healthy",
		"block_number": blockNumber,
	})
}

func handleOwnersPowder(w http.ResponseWriter, r *http.Request) {
	startTime := time.Now()

	// Parse form data
	err := r.ParseForm()
	if err != nil {
		http.Error(w, "Error parsing form data", http.StatusBadRequest)
		return
	}

	collectionAddress := r.FormValue("collection_address")
	if collectionAddress == "" {
		w.Write([]byte(`<div id="results" class="error">Error: Collection address not provided.</div>`))
		return
	}

	// Validate address format
	if !common.IsHexAddress(collectionAddress) {
		w.Write([]byte(`<div id="results" class="error">Error: Invalid collection address format.</div>`))
		return
	}

	// Connect to Ethereum node
	client, err := ethclient.Dial(NodeURL)
	if err != nil {
		w.Write([]byte(`<div id="results" class="error">Error: Failed to connect to Ethereum node.</div>`))
		log.Printf("Failed to connect to Ethereum node: %v", err)
		return
	}
	defer client.Close()

	// Get current block
	currentBlock, err := client.BlockNumber(context.Background())
	if err != nil {
		w.Write([]byte(`<div id="results" class="error">Error: Failed to get current block number.</div>`))
		log.Printf("Failed to get current block number: %v", err)
		return
	}

	log.Printf("Current Block: %d", currentBlock)

	// Calculate past blocks
	secondsIn6Months := int64(6 * 30 * 24 * 60 * 60)
	secondsIn1Year := int64(12 * 30 * 24 * 60 * 60)
	blocksIn6Months := secondsIn6Months / AvgBlockTimeSeconds
	blocksIn1Year := secondsIn1Year / AvgBlockTimeSeconds

	block6mAgo := int64(currentBlock) - blocksIn6Months
	if block6mAgo < 0 {
		block6mAgo = 0
	}

	block1yAgo := int64(currentBlock) - blocksIn1Year
	if block1yAgo < 0 {
		block1yAgo = 0
	}

	// Create target blocks map
	targetBlocks := map[string]int64{
		"-1 Year":   block1yAgo,
		"-6 Months": block6mAgo,
		"Now":       int64(currentBlock),
	}

	// Parse ABI
	parsedABI, err := abi.JSON(strings.NewReader(minimalERC721ABI))
	if err != nil {
		w.Write([]byte(`<div id="results" class="error">Error: Failed to parse contract ABI.</div>`))
		log.Printf("Failed to parse contract ABI: %v", err)
		return
	}

	// Set up contract address
	contractAddress := common.HexToAddress(collectionAddress)

	// Process blocks in parallel
	resultsData, totalFetchTime := fetchAllBlocksInParallel(client, parsedABI, contractAddress, targetBlocks)

	// Process errors
	var allErrors []string
	for _, item := range resultsData {
		if !item.Data.Success {
			for _, errMsg := range item.Data.Errors {
				allErrors = append(allErrors, fmt.Sprintf("[%s @%d] %s", item.Label, item.Block, errMsg))
			}
		}
	}

	// Prepare data for graphing
	timeLabels := make([]string, 0)
	powderPerOwnerValues := make([]float64, 0)
	successfulFetches := 0

	for _, item := range resultsData {
		if item.Data.Success {
			successfulFetches++
			timeLabels = append(timeLabels, item.Label)
			
			// Parse balance
			balanceEth, ok := new(big.Float).SetString(item.Data.BalanceEth)
			if !ok {
				log.Printf("Error parsing balance: %s", item.Data.BalanceEth)
				continue
			}
			
			// Calculate powder per owner
			var powderPerOwner float64
			if item.Data.Owners > 0 {
				powderPerOwnerBig := new(big.Float).Quo(balanceEth, big.NewFloat(float64(item.Data.Owners)))
				powderPerOwner, _ = powderPerOwnerBig.Float64()
			}
			
			powderPerOwnerValues = append(powderPerOwnerValues, powderPerOwner)
		}
	}

	// Generate graph HTML (if we have data)
	graphHTML := "<p>Not enough data points to generate graph.</p>"
	if len(timeLabels) > 1 {
		// Here you would generate a Plotly graph - this would need a Go Plotly library
		// For now we'll use a simple placeholder
		graphHTML = generatePlotlyHTML(timeLabels, powderPerOwnerValues)
	} else if len(timeLabels) == 1 {
		graphHTML = fmt.Sprintf("<p>Only got data for one time point (%s). Cannot draw a line graph.</p>", timeLabels[0])
	}

	// Construct HTML response
	responseHTML := "<div id=\"results\">"
	responseHTML += "<h3>Summary Over Time</h3>"
	responseHTML += "<table border=\"1\" style=\"width:100%; border-collapse: collapse; margin-bottom: 1em;\">"
	responseHTML += "<tr><th>Time Point</th><th>Block</th><th>Unique Owners</th><th>Total Powder (ETH)</th><th>Avg Powder (ETH)</th><th>Checked Tokens</th><th>Status</th></tr>"

	totalOwners := 0
	totalBalance := big.NewFloat(0)
	totalChecked := 0

	for _, item := range resultsData {
		status := "Success"
		if !item.Data.Success {
			status = "<span class='error'>Failed</span>"
		}

		balanceEth, _ := new(big.Float).SetString(item.Data.BalanceEth)
		
		// Calculate average powder
		avgPowder := big.NewFloat(0)
		if item.Data.Owners > 0 {
			avgPowder = new(big.Float).Quo(balanceEth, big.NewFloat(float64(item.Data.Owners)))
		}

		// Format for display
		balanceStr := fmt.Sprintf("%.4f", balanceEth)
		avgPowderStr := fmt.Sprintf("%.4f", avgPowder)

		responseHTML += fmt.Sprintf("<tr><td>%s</td><td>%d</td><td>%d</td><td>%s</td><td>%s</td><td>%d</td><td>%s</td></tr>",
			item.Label, item.Block, item.Data.Owners, balanceStr, avgPowderStr, item.Data.CheckedTokens, status)

		totalOwners += item.Data.Owners
		totalBalance.Add(totalBalance, balanceEth)
		totalChecked += item.Data.CheckedTokens
	}

	responseHTML += "</table>"
	responseHTML += "<h3>Average Owner Powder Trend</h3>"
	responseHTML += graphHTML

	// Add warnings/errors if any occurred
	anyTokenLimitHit := false
	for _, res := range resultsData {
		if res.Data.Success && res.Data.CheckedTokens == MaxTokensToCheck {
			anyTokenLimitHit = true
			break
		}
	}

	if anyTokenLimitHit {
		responseHTML += fmt.Sprintf("<p class=\"warning\">Warning: MAX_TOKENS_TO_CHECK (%d) limit was hit for one or more time points. Results may be incomplete.</p>", MaxTokensToCheck)
	}

	if len(allErrors) > 0 {
		responseHTML += "<p class=\"error\">Encountered errors during data fetching:</p><ul>"
		for _, err := range allErrors[:min(10, len(allErrors))] {
			responseHTML += fmt.Sprintf("<li>%s</li>", err)
		}
		if len(allErrors) > 10 {
			responseHTML += fmt.Sprintf("<li>... (%d more errors not shown)</li>", len(allErrors)-10)
		}
		responseHTML += "</ul>"
	}

	responseHTML += "</div>"

	// Timing & Return
	totalDuration := time.Since(startTime).Seconds()
	log.Printf("Total request time for %s: %.2f seconds", collectionAddress, totalDuration)
	log.Printf("  - Total data fetch duration across blocks: %.2f", totalFetchTime)

	w.Write([]byte(responseHTML))
}

func fetchAllBlocksInParallel(client *ethclient.Client, parsedABI abi.ABI, contractAddress common.Address, targetBlocks map[string]int64) ([]TimePoint, float64) {
	var wg sync.WaitGroup
	resultsChan := make(chan TimePoint, len(targetBlocks))
	totalFetchTime := 0.0

	for label, blockNum := range targetBlocks {
		wg.Add(1)
		go func(label string, blockNum int64) {
			defer wg.Done()

			fetchStartTime := time.Now()
			log.Printf("Fetching data for block: %d...", blockNum)

			result := fetchDataAtBlock(client, parsedABI, contractAddress, blockNum)
			fetchDuration := time.Since(fetchStartTime).Seconds()

			log.Printf("Block fetch for '%s' (%d) took %.2fs", label, blockNum, fetchDuration)
			resultsChan <- TimePoint{
				Label: label,
				Block: blockNum,
				Data:  result,
			}
		}(label, blockNum)
	}

	// Wait for all goroutines to complete
	wg.Wait()
	close(resultsChan)

	// Collect results
	var resultsData []TimePoint
	for result := range resultsChan {
		resultsData = append(resultsData, result)
		totalFetchTime += result.Data.OwnerOfDuration + result.Data.BalanceDuration
	}

	return resultsData, totalFetchTime
}

func fetchDataAtBlock(client *ethclient.Client, parsedABI abi.ABI, contractAddress common.Address, blockNumber int64) BlockResult {
	startTime := time.Now()
	fetchErrors := make([]string, 0)
	var ownerOfDuration, balanceDuration float64

	ctx, cancel := context.WithTimeout(context.Background(), RequestTimeout)
	defer cancel()

	blockNumberHex := fmt.Sprintf("0x%x", blockNumber)

	// Get totalSupply
	totalSupplyData, err := parsedABI.Pack("totalSupply")
	if err != nil {
		log.Printf("Error packing totalSupply: %v", err)
		fetchErrors = append(fetchErrors, fmt.Sprintf("Error packing totalSupply: %v", err))
		return BlockResult{
			Owners:          0,
			BalanceEth:      "0",
			CheckedTokens:   0,
			Errors:          fetchErrors,
			OwnerOfDuration: 0,
			BalanceDuration: 0,
			Block:           blockNumber,
			Success:         false,
		}
	}

	callMsg := ethereum.CallMsg{
		To:   &contractAddress,
		Data: totalSupplyData,
	}

	totalSupplyResult, err := client.CallContract(ctx, callMsg, big.NewInt(blockNumber))
	if err != nil {
		log.Printf("Error calling totalSupply: %v", err)
		fetchErrors = append(fetchErrors, fmt.Sprintf("Error calling totalSupply: %v", err))
		return BlockResult{
			Owners:          0,
			BalanceEth:      "0",
			CheckedTokens:   0,
			Errors:          fetchErrors,
			OwnerOfDuration: 0,
			BalanceDuration: 0,
			Block:           blockNumber,
			Success:         false,
		}
	}

	totalSupply := new(big.Int).SetBytes(totalSupplyResult)
	tokensToCheck := min(int(totalSupply.Int64()), MaxTokensToCheck)

	log.Printf("  [Block %d] Total supply: %s. Checking first %d tokens.", blockNumber, totalSupply.String(), tokensToCheck)

	// --- Batch OwnerOf ---
	startOwnerOf := time.Now()
	uniqueOwners := make(map[common.Address]struct{})
	checkedTokenCount := 0

	// Process in smaller batches (e.g., 50 at a time)
	batchSize := 50
	for i := 0; i < tokensToCheck; i += batchSize {
		batchEnd := min(i+batchSize, tokensToCheck)
		
		// Create batch requests
		batchReq := make([]rpc.BatchElem, 0, batchEnd-i)
		tokenIDs := make([]int, 0, batchEnd-i)
		
		for tokenID := i; tokenID < batchEnd; tokenID++ {
			// Pack the ownerOf function call
			ownerOfData, err := parsedABI.Pack("ownerOf", big.NewInt(int64(tokenID)))
			if err != nil {
				log.Printf("Error packing ownerOf for token %d: %v", tokenID, err)
				continue
			}
			
			// Add to batch
			tokenIDs = append(tokenIDs, tokenID)
			batchReq = append(batchReq, rpc.BatchElem{
				Method: "eth_call",
				Args: []interface{}{
					map[string]interface{}{
						"to":   contractAddress.Hex(),
						"data": "0x" + common.Bytes2Hex(ownerOfData),
					},
					blockNumberHex,
				},
				Result: new(string),
			})
		}
		
		// Send batch request
		rawClient, err := rpc.Dial(NodeURL)
		if err != nil {
			log.Printf("Error connecting to RPC for batch request: %v", err)
			fetchErrors = append(fetchErrors, fmt.Sprintf("Error connecting to RPC: %v", err))
			continue
		}
		
		err = rawClient.BatchCall(batchReq)
		if err != nil {
			log.Printf("Error in batch call: %v", err)
			fetchErrors = append(fetchErrors, fmt.Sprintf("Error in batch call: %v", err))
			continue
		}
		
		// Process results
		for j, elem := range batchReq {
			if elem.Error != nil {
				log.Printf("Error for token %d: %v", tokenIDs[j], elem.Error)
				continue
			}
			
			result := *elem.Result.(*string)
			if result == "0x" || len(result) < 2+40 { // "0x" + 40 hex chars for address
				continue
			}
			
			// Extract address (last 20 bytes)
			addressHex := result[len(result)-40:]
			owner := common.HexToAddress("0x" + addressHex)
			uniqueOwners[owner] = struct{}{}
			checkedTokenCount++
		}
		
		if i > 0 && i%50 == 0 {
			log.Printf("  [Block %d] Checked ownerOf up to token ID: %d", blockNumber, i)
		}
	}

	ownerOfDuration = time.Since(startOwnerOf).Seconds()
	log.Printf("  [Block %d] Found %d owners in %.2fs.", blockNumber, len(uniqueOwners), ownerOfDuration)

	// --- Batch Balance ---
	startBalance := time.Now()
	totalBalanceWei := big.NewInt(0)

	// Get list of owners
	owners := make([]common.Address, 0, len(uniqueOwners))
	for owner := range uniqueOwners {
		owners = append(owners, owner)
	}

	// Process in smaller chunks to avoid request size limits
	maxChunkSize := 50
	for i := 0; i < len(owners); i += maxChunkSize {
		end := min(i+maxChunkSize, len(owners))
		chunk := owners[i:end]
		
		// Create batch request for balance
		balanceBatch := make([]rpc.BatchElem, 0, len(chunk))
		
		for _, owner := range chunk {
			balanceBatch = append(balanceBatch, rpc.BatchElem{
				Method: "eth_getBalance",
				Args:   []interface{}{owner.Hex(), blockNumberHex},
				Result: new(string),
			})
		}
		
		// Send batch request
		rawClient, err := rpc.Dial(NodeURL)
		if err != nil {
			log.Printf("Error connecting to RPC for balance batch: %v", err)
			fetchErrors = append(fetchErrors, fmt.Sprintf("Error connecting to RPC for balance: %v", err))
			continue
		}
		
		err = rawClient.BatchCall(balanceBatch)
		if err != nil {
			log.Printf("Error in balance batch call: %v", err)
			fetchErrors = append(fetchErrors, fmt.Sprintf("Error in balance batch call: %v", err))
			continue
		}
		
		// Process results
		for _, elem := range balanceBatch {
			if elem.Error != nil {
				log.Printf("Error getting balance: %v", elem.Error)
				continue
			}
			
			hexBalance := *elem.Result.(*string)
			if len(hexBalance) < 2 { // At least "0x"
				continue
			}
			
			// Convert hex to big int
			balanceWei, success := new(big.Int).SetString(hexBalance[2:], 16)
			if !success {
				log.Printf("Error parsing balance: %s", hexBalance)
				continue
			}
			
			totalBalanceWei.Add(totalBalanceWei, balanceWei)
		}
	}

	balanceDuration = time.Since(startBalance).Seconds()
	log.Printf("  [Block %d] Checked balances in %.2fs.", blockNumber, balanceDuration)

	// Convert wei to eth
	weiPerEth := new(big.Int).Exp(big.NewInt(10), big.NewInt(18), nil)
	totalBalanceEth := new(big.Float).Quo(
		new(big.Float).SetInt(totalBalanceWei),
		new(big.Float).SetInt(weiPerEth),
	)

	log.Printf("Finished fetching data for block %d. Total time: %.2fs", blockNumber, time.Since(startTime).Seconds())

	return BlockResult{
		Owners:          len(uniqueOwners),
		BalanceEth:      totalBalanceEth.Text('f', 18), // 18 is precision
		CheckedTokens:   checkedTokenCount,
		Errors:          fetchErrors,
		OwnerOfDuration: ownerOfDuration,
		BalanceDuration: balanceDuration,
		Block:           blockNumber,
		Success:         true,
	}
}

func handleSSEOwnersPowder(w http.ResponseWriter, r *http.Request) {
	// Set headers for SSE
	w.Header().Set("Content-Type", "text/event-stream")
	w.Header().Set("Cache-Control", "no-cache")
	w.Header().Set("Connection", "keep-alive")
	w.Header().Set("Access-Control-Allow-Origin", "*")

	// Get collection address
	collectionAddress := r.URL.Query().Get("collection_address")
	if collectionAddress == "" {
		fmt.Fprintf(w, "data: %s\n\n", `{"error": "Collection address not provided"}`)
		return
	}

	// Connect to Ethereum
	client, err := ethclient.Dial(NodeURL)
	if err != nil {
		fmt.Fprintf(w, "data: %s\n\n", fmt.Sprintf(`{"error": "Failed to connect to Ethereum node: %v"}`, err))
		return
	}
	defer client.Close()

	// Parse ABI
	parsedABI, err := abi.JSON(strings.NewReader(minimalERC721ABI))
	if err != nil {
		fmt.Fprintf(w, "data: %s\n\n", fmt.Sprintf(`{"error": "Failed to parse ABI: %v"}`, err))
		return
	}

	// Get current block and calculate historical blocks
	currentBlock, err := client.BlockNumber(context.Background())
	if err != nil {
		fmt.Fprintf(w, "data: %s\n\n", fmt.Sprintf(`{"error": "Failed to get current block: %v"}`, err))
		return
	}

	// Calculate blocks
	secondsIn6Months := int64(6 * 30 * 24 * 60 * 60)
	secondsIn1Year := int64(12 * 30 * 24 * 60 * 60)
	blocksIn6Months := secondsIn6Months / AvgBlockTimeSeconds
	blocksIn1Year := secondsIn1Year / AvgBlockTimeSeconds

	block6mAgo := max(0, int64(currentBlock)-blocksIn6Months)
	block1yAgo := max(0, int64(currentBlock)-blocksIn1Year)

	targetBlocks := map[string]int64{
		"-1 Year":   block1yAgo,
		"-6 Months": block6mAgo,
		"Now":       int64(currentBlock),
	}

	contractAddr := common.HexToAddress(collectionAddress)

	// Process blocks and stream results
	completedBlocks := 0
	results := make(map[string]TimePoint)

	// Process one block at a time and send updates
	for label, blockNum := range targetBlocks {
		result := fetchDataAtBlock(client, parsedABI, contractAddr, blockNum)
		completedBlocks++

		timePoint := TimePoint{
			Label: label,
			Block: blockNum,
			Data:  result,
		}
		results[label] = timePoint

		// Send partial results
		jsonData, _ := json.Marshal(map[string]interface{}{
			"label":    label,
			"results":  results,
			"complete": completedBlocks == len(targetBlocks),
		})
		fmt.Fprintf(w, "data: %s\n\n", jsonData)
		w.(http.Flusher).Flush() // Ensure data is sent immediately
	}

	// Final message
	jsonData, _ := json.Marshal(map[string]interface{}{
		"complete": true,
		"results":  results,
	})
	fmt.Fprintf(w, "data: %s\n\n", jsonData)
}

// Helpers
func min(a, b int) int {
	if a < b {
		return a
	}
	return b
}

func max(a, b int64) int64 {
	if a > b {
		return a
	}
	return b
}

func generatePlotlyHTML(labels []string, values []float64) string {
	// This is a simplified placeholder - in a real implementation, 
	// you would use a Go library to generate Plotly JS code or 
	// pass the data to the frontend for rendering
	dataPoints := make([]string, len(labels))
	for i := range labels {
		dataPoints[i] = fmt.Sprintf("{x:'%s', y:%.6f}", labels[i], values[i])
	}

	return fmt.Sprintf(`
	<div id="plotlyChart" style="width:100%%; height:400px;"></div>
	<script>
		var data = [
			{
				x: %v,
				y: %v,
				type: 'scatter',
				mode: 'lines+markers'
			}
		];
		var layout = {
			title: 'Average Owner Powder (ETH) Over Time',
			xaxis: {title: 'Time Point'},
			yaxis: {title: 'Avg ETH per Owner'},
			margin: {l: 40, r: 20, t: 40, b: 30}
		};
		Plotly.newPlot('plotlyChart', data, layout);
	</script>
	`, labels, values)
}