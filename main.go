package main

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"io/ioutil"
	"log"
	"math/big"
	"net/http"
	"os"
	"strconv"
	"strings"
	"sync"
	"time"

	"github.com/ethereum/go-ethereum"
	"github.com/ethereum/go-ethereum/accounts/abi"
	"github.com/ethereum/go-ethereum/common"
	"github.com/ethereum/go-ethereum/ethclient"
	"github.com/ethereum/go-ethereum/rpc"
	"github.com/gin-contrib/cors"
	"github.com/gin-gonic/gin"
	"github.com/shopspring/decimal"
)

type Config struct {
	NodeURL               string
	MaxTokensToCheck      int
	RequestTimeout        time.Duration
	AvgBlockTimeSeconds   int
	OwnerBatchSize        int
	BalanceBatchSize      int
	ConcurrentBatches     int
	MaxConcurrentConns    int
	Port                  string
}

type EthereumClient struct {
	client     *ethclient.Client
	rpcClient  *rpc.Client
	httpClient *http.Client
	config     *Config
}

type BlockResult struct {
	Label             string          `json:"label"`
	Block             uint64          `json:"block"`
	Owners            int             `json:"owners"`
	BalanceETH        decimal.Decimal `json:"balance_eth"`
	CheckedTokens     int             `json:"checked_tokens"`
	Success           bool            `json:"success"`
	Errors            []string        `json:"errors"`
	OwnerOfDuration   float64         `json:"ownerof_duration"`
	BalanceDuration   float64         `json:"balance_duration"`
}

type ProgressUpdate struct {
	Type    string `json:"type"`
	Message string `json:"message"`
	Step    int    `json:"step"`
	Total   int    `json:"total"`
	HTML    string `json:"html,omitempty"`
}

type NodeStatus struct {
	Connected   bool   `json:"connected"`
	BlockNumber uint64 `json:"block_number,omitempty"`
	Error       string `json:"error,omitempty"`
}

type RPCRequest struct {
	JSONRPC string        `json:"jsonrpc"`
	Method  string        `json:"method"`
	Params  []interface{} `json:"params"`
	ID      interface{}   `json:"id"`
}

type RPCResponse struct {
	JSONRPC string      `json:"jsonrpc"`
	Result  interface{} `json:"result"`
	Error   *RPCError   `json:"error"`
	ID      interface{} `json:"id"`
}

type RPCError struct {
	Code    int    `json:"code"`
	Message string `json:"message"`
}

var (
	ethClient *EthereumClient
	config    *Config
)

const erc721ABI = `[
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

func loadConfig() *Config {
	nodeURL := getEnvOrDefault("NODE_URL", "http://192.168.10.8:8545")
	maxTokens, _ := strconv.Atoi(getEnvOrDefault("MAX_TOKENS_TO_CHECK", "11000"))
	requestTimeout, _ := strconv.Atoi(getEnvOrDefault("REQUEST_TIMEOUT", "240"))
	avgBlockTime, _ := strconv.Atoi(getEnvOrDefault("AVG_BLOCK_TIME_SECONDS", "12"))
	port := getEnvOrDefault("PORT", "5000")

	return &Config{
		NodeURL:               nodeURL,
		MaxTokensToCheck:      maxTokens,
		RequestTimeout:        time.Duration(requestTimeout) * time.Second,
		AvgBlockTimeSeconds:   avgBlockTime,
		OwnerBatchSize:        100, // Erigon limit
		BalanceBatchSize:      100, // Erigon limit
		ConcurrentBatches:     20,  // Increased for Go concurrency
		MaxConcurrentConns:    100, // Much higher for Go
		Port:                  port,
	}
}

func getEnvOrDefault(key, defaultValue string) string {
	if value := os.Getenv(key); value != "" {
		return value
	}
	return defaultValue
}

func newEthereumClient(cfg *Config) (*EthereumClient, error) {
	// Create HTTP client with connection pooling
	httpClient := &http.Client{
		Timeout: cfg.RequestTimeout,
		Transport: &http.Transport{
			MaxIdleConns:        cfg.MaxConcurrentConns,
			MaxIdleConnsPerHost: cfg.MaxConcurrentConns,
			IdleConnTimeout:     30 * time.Second,
		},
	}

	// Create RPC client
	rpcClient, err := rpc.DialHTTP(cfg.NodeURL)
	if err != nil {
		return nil, fmt.Errorf("failed to connect to RPC: %w", err)
	}

	// Create eth client
	client, err := ethclient.Dial(cfg.NodeURL)
	if err != nil {
		return nil, fmt.Errorf("failed to connect to Ethereum client: %w", err)
	}

	return &EthereumClient{
		client:     client,
		rpcClient:  rpcClient,
		httpClient: httpClient,
		config:     cfg,
	}, nil
}

func (ec *EthereumClient) batchGetOwners(ctx context.Context, contractAddress common.Address, tokenIDs []int, blockNumber uint64) (map[common.Address]bool, error) {
	if len(tokenIDs) == 0 {
		return make(map[common.Address]bool), nil
	}

	// Parse ABI
	parsedABI, err := abi.JSON(strings.NewReader(erc721ABI))
	if err != nil {
		return nil, fmt.Errorf("failed to parse ABI: %w", err)
	}

	// Create batch requests
	var requests []RPCRequest
	for i, tokenID := range tokenIDs {
		// Encode the ownerOf call
		data, err := parsedABI.Pack("ownerOf", big.NewInt(int64(tokenID)))
		if err != nil {
			log.Printf("Error encoding ownerOf for token %d: %v", tokenID, err)
			continue
		}

		requests = append(requests, RPCRequest{
			JSONRPC: "2.0",
			Method:  "eth_call",
			Params: []interface{}{
				map[string]interface{}{
					"to":   contractAddress.Hex(),
					"data": "0x" + common.Bytes2Hex(data),
				},
				fmt.Sprintf("0x%x", blockNumber),
			},
			ID: i,
		})
	}

	// Send batch request
	owners := make(map[common.Address]bool)
	if len(requests) == 0 {
		return owners, nil
	}

	// Convert to JSON
	requestBytes, err := json.Marshal(requests)
	if err != nil {
		return nil, fmt.Errorf("failed to marshal batch request: %w", err)
	}

	// Send HTTP request
	resp, err := ec.httpClient.Post(ec.config.NodeURL, "application/json", bytes.NewBuffer(requestBytes))
	if err != nil {
		return nil, fmt.Errorf("failed to send batch request: %w", err)
	}
	defer resp.Body.Close()

	// Parse response
	var responses []RPCResponse
	if err := json.NewDecoder(resp.Body).Decode(&responses); err != nil {
		return nil, fmt.Errorf("failed to decode batch response: %w", err)
	}

	// Process results
	for _, response := range responses {
		if response.Error != nil {
			log.Printf("RPC error in batch response: %s", response.Error.Message)
			continue
		}

		if response.Result == nil {
			continue
		}

		// Extract address from hex result
		if resultStr, ok := response.Result.(string); ok && len(resultStr) >= 42 {
			if addr := common.HexToAddress(resultStr); addr != (common.Address{}) {
				owners[addr] = true
			}
		}
	}

	return owners, nil
}

func (ec *EthereumClient) batchGetBalances(ctx context.Context, addresses []common.Address, blockNumber uint64) (*big.Int, error) {
	if len(addresses) == 0 {
		return big.NewInt(0), nil
	}

	// Create batch requests
	var requests []RPCRequest
	for i, addr := range addresses {
		requests = append(requests, RPCRequest{
			JSONRPC: "2.0",
			Method:  "eth_getBalance",
			Params: []interface{}{
				addr.Hex(),
				fmt.Sprintf("0x%x", blockNumber),
			},
			ID: i,
		})
	}

	// Send batch request
	requestBytes, err := json.Marshal(requests)
	if err != nil {
		return nil, fmt.Errorf("failed to marshal balance batch request: %w", err)
	}

	resp, err := ec.httpClient.Post(ec.config.NodeURL, "application/json", bytes.NewBuffer(requestBytes))
	if err != nil {
		return nil, fmt.Errorf("failed to send balance batch request: %w", err)
	}
	defer resp.Body.Close()

	var responses []RPCResponse
	if err := json.NewDecoder(resp.Body).Decode(&responses); err != nil {
		return nil, fmt.Errorf("failed to decode balance batch response: %w", err)
	}

	// Sum all balances
	totalBalance := big.NewInt(0)
	for _, response := range responses {
		if response.Error != nil {
			log.Printf("RPC error in balance batch response: %s", response.Error.Message)
			continue
		}

		if response.Result == nil {
			continue
		}

		if balanceStr, ok := response.Result.(string); ok {
			if balance, ok := new(big.Int).SetString(balanceStr[2:], 16); ok { // Remove 0x prefix
				totalBalance.Add(totalBalance, balance)
			}
		}
	}

	return totalBalance, nil
}

func (ec *EthereumClient) fetchDataAtBlock(ctx context.Context, contractAddress common.Address, blockNumber uint64, progressChan chan<- string) (*BlockResult, error) {
	startTime := time.Now()
	var errors []string

	log.Printf("Fetching data for block: %d", blockNumber)

	// Get total supply
	if progressChan != nil {
		progressChan <- fmt.Sprintf("Getting total supply at block %d...", blockNumber)
	}

	parsedABI, err := abi.JSON(strings.NewReader(erc721ABI))
	if err != nil {
		return nil, fmt.Errorf("failed to parse ABI: %w", err)
	}

	data, err := parsedABI.Pack("totalSupply")
	if err != nil {
		return nil, fmt.Errorf("failed to pack totalSupply call: %w", err)
	}

	msg := ethereum.CallMsg{
		To:   &contractAddress,
		Data: data,
	}

	result, err := ec.client.CallContract(ctx, msg, new(big.Int).SetUint64(blockNumber))
	if err != nil {
		return nil, fmt.Errorf("failed to call totalSupply: %w", err)
	}

	totalSupply := new(big.Int).SetBytes(result)
	tokensToCheck := int(totalSupply.Int64())
	if tokensToCheck > ec.config.MaxTokensToCheck {
		tokensToCheck = ec.config.MaxTokensToCheck
	}

	log.Printf("Block %d: Total supply: %s. Checking first %d tokens", blockNumber, totalSupply.String(), tokensToCheck)
	if progressChan != nil {
		progressChan <- fmt.Sprintf("Found %s tokens. Checking first %d...", totalSupply.String(), tokensToCheck)
	}

	// Fetch owners in parallel batches
	ownerOfStart := time.Now()
	if progressChan != nil {
		progressChan <- fmt.Sprintf("Fetching owners for %d tokens...", tokensToCheck)
	}

	uniqueOwners := make(map[common.Address]bool)
	var mu sync.Mutex
	var wg sync.WaitGroup

	// Create semaphore for concurrent batches
	sem := make(chan struct{}, ec.config.ConcurrentBatches)

	// Process in batches
	batchSize := ec.config.OwnerBatchSize
	totalBatches := (tokensToCheck + batchSize - 1) / batchSize

	for i := 0; i < tokensToCheck; i += batchSize {
		wg.Add(1)
		go func(start int) {
			defer wg.Done()
			sem <- struct{}{} // Acquire semaphore
			defer func() { <-sem }() // Release semaphore

			end := start + batchSize
			if end > tokensToCheck {
				end = tokensToCheck
			}

			tokenBatch := make([]int, end-start)
			for j := start; j < end; j++ {
				tokenBatch[j-start] = j
			}

			batchNum := (start / batchSize) + 1
			if progressChan != nil {
				progressChan <- fmt.Sprintf("Processing token batch %d/%d (tokens %d-%d)...", batchNum, totalBatches, start, end-1)
			}

			batchOwners, err := ec.batchGetOwners(ctx, contractAddress, tokenBatch, blockNumber)
			if err != nil {
				errMsg := fmt.Sprintf("Error in batch_get_owners(IDs %d-%d, Block %d): %v", start, end-1, blockNumber, err)
				log.Println(errMsg)
				mu.Lock()
				if len(errors) < 5 {
					errors = append(errors, errMsg)
				}
				mu.Unlock()
				return
			}

			mu.Lock()
			for owner := range batchOwners {
				uniqueOwners[owner] = true
			}
			mu.Unlock()
		}(i)
	}

	wg.Wait()

	ownerOfDuration := time.Since(ownerOfStart).Seconds()
	log.Printf("Block %d: Found %d owners in %.2fs", blockNumber, len(uniqueOwners), ownerOfDuration)
	if progressChan != nil {
		progressChan <- fmt.Sprintf("Found %d unique owners. Now fetching balances...", len(uniqueOwners))
	}

	// Fetch balances in parallel batches
	balanceStart := time.Now()
	if progressChan != nil {
		progressChan <- fmt.Sprintf("Calculating ETH balances for %d addresses...", len(uniqueOwners))
	}

	addresses := make([]common.Address, 0, len(uniqueOwners))
	for addr := range uniqueOwners {
		addresses = append(addresses, addr)
	}

	totalBalance := big.NewInt(0)
	balanceBatchSize := ec.config.BalanceBatchSize

	var balanceMu sync.Mutex
	var balanceWg sync.WaitGroup
	balanceSem := make(chan struct{}, ec.config.ConcurrentBatches)

	for i := 0; i < len(addresses); i += balanceBatchSize {
		balanceWg.Add(1)
		go func(start int) {
			defer balanceWg.Done()
			balanceSem <- struct{}{}
			defer func() { <-balanceSem }()

			end := start + balanceBatchSize
			if end > len(addresses) {
				end = len(addresses)
			}

			batchAddresses := addresses[start:end]
			batchBalance, err := ec.batchGetBalances(ctx, batchAddresses, blockNumber)
			if err != nil {
				errMsg := fmt.Sprintf("Error in batch_get_balances(Block %d): %v", blockNumber, err)
				log.Println(errMsg)
				balanceMu.Lock()
				if len(errors) < 5 {
					errors = append(errors, errMsg)
				}
				balanceMu.Unlock()
				return
			}

			balanceMu.Lock()
			totalBalance.Add(totalBalance, batchBalance)
			balanceMu.Unlock()
		}(i)
	}

	balanceWg.Wait()

	balanceDuration := time.Since(balanceStart).Seconds()
	log.Printf("Block %d: Checked balances in %.2fs", blockNumber, balanceDuration)

	// Convert to ETH
	ethBalance := decimal.NewFromBigInt(totalBalance, -18) // Wei to ETH conversion

	if progressChan != nil {
		progressChan <- fmt.Sprintf("Block %d complete: %d owners, %s ETH total", blockNumber, len(uniqueOwners), ethBalance.String())
	}

	log.Printf("Finished fetching data for block %d. Total time: %.2fs", blockNumber, time.Since(startTime).Seconds())

	return &BlockResult{
		Block:             blockNumber,
		Owners:            len(uniqueOwners),
		BalanceETH:        ethBalance,
		CheckedTokens:     tokensToCheck,
		Success:           true,
		Errors:            errors,
		OwnerOfDuration:   ownerOfDuration,
		BalanceDuration:   balanceDuration,
	}, nil
}

func (ec *EthereumClient) getBlockNumber(ctx context.Context) (uint64, error) {
	return ec.client.BlockNumber(ctx)
}

// Handler functions
func nodeStatusHandler(c *gin.Context) {
	ctx := context.Background()
	blockNumber, err := ethClient.getBlockNumber(ctx)
	if err != nil {
		c.JSON(http.StatusOK, NodeStatus{
			Connected: false,
			Error:     err.Error(),
		})
		return
	}

	c.JSON(http.StatusOK, NodeStatus{
		Connected:   true,
		BlockNumber: blockNumber,
	})
}

func indexHandler(c *gin.Context) {
	htmlContent, err := ioutil.ReadFile("web/index.html")
	if err != nil {
		c.String(http.StatusNotFound, "Error: index.html not found.")
		return
	}
	c.Data(http.StatusOK, "text/html; charset=utf-8", htmlContent)
}

func getOwnersPowderHandler(c *gin.Context) {
	ctx := context.Background()
	startTime := time.Now()

	// Check connection
	_, err := ethClient.getBlockNumber(ctx)
	if err != nil {
		c.Data(http.StatusOK, "text/html", []byte(`<div id="results" class="error">Error: Ethereum node connection lost. Please check backend logs.</div>`))
		return
	}

	collectionAddressStr := c.PostForm("collection_address")
	if collectionAddressStr == "" {
		c.Data(http.StatusOK, "text/html", []byte(`<div id="results" class="error">Error: Collection address not provided.</div>`))
		return
	}

	if !common.IsHexAddress(collectionAddressStr) {
		c.Data(http.StatusOK, "text/html", []byte(fmt.Sprintf(`<div id="results" class="error">Error: Invalid collection address format: %s</div>`, collectionAddressStr)))
		return
	}

	collectionAddress := common.HexToAddress(collectionAddressStr)

	// Calculate past block numbers
	currentBlock, err := ethClient.getBlockNumber(ctx)
	if err != nil {
		c.Data(http.StatusOK, "text/html", []byte(`<div id="results" class="error">Error: Could not get current block number.</div>`))
		return
	}

	log.Printf("Current Block: %d", currentBlock)

	secondsIn6Months := 6 * 30 * 24 * 60 * 60
	secondsIn1Year := 12 * 30 * 24 * 60 * 60
	blocksIn6Months := uint64(secondsIn6Months / config.AvgBlockTimeSeconds)
	blocksIn1Year := uint64(secondsIn1Year / config.AvgBlockTimeSeconds)

	var block6mAgo, block1yAgo uint64
	if currentBlock > blocksIn6Months {
		block6mAgo = currentBlock - blocksIn6Months
	}
	if currentBlock > blocksIn1Year {
		block1yAgo = currentBlock - blocksIn1Year
	}

	targetBlocks := map[string]uint64{
		"-1 Year":   block1yAgo,
		"-6 Months": block6mAgo,
		"Now":       currentBlock,
	}

	// Fetch all blocks in parallel
	var wg sync.WaitGroup
	results := make(map[string]*BlockResult)
	var mu sync.Mutex

	for label, blockNum := range targetBlocks {
		wg.Add(1)
		go func(l string, bn uint64) {
			defer wg.Done()
			result, err := ethClient.fetchDataAtBlock(ctx, collectionAddress, bn, nil)
			if err != nil {
				log.Printf("Error fetching data for block %d (%s): %v", bn, l, err)
				result = &BlockResult{
					Label:   l,
					Block:   bn,
					Success: false,
					Errors:  []string{fmt.Sprintf("Error: %v", err)},
				}
			}
			result.Label = l

			mu.Lock()
			results[l] = result
			mu.Unlock()
		}(label, blockNum)
	}

	wg.Wait()

	// Generate HTML response
	html := generateResultsHTML(results)

	totalDuration := time.Since(startTime).Seconds()
	log.Printf("Total request time for %s: %.2f seconds", collectionAddressStr, totalDuration)

	c.Data(http.StatusOK, "text/html", []byte(html))
}

func progressStreamHandler(c *gin.Context) {
	collectionAddressStr := c.Query("collection_address")
	if collectionAddressStr == "" || !common.IsHexAddress(collectionAddressStr) {
		c.Data(http.StatusOK, "text/event-stream", []byte(`data: {"error": "Invalid parameters"}\n\n`))
		return
	}

	c.Header("Content-Type", "text/event-stream")
	c.Header("Cache-Control", "no-cache")
	c.Header("Connection", "keep-alive")
	c.Header("Access-Control-Allow-Origin", "*")

	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()

	// Check if client disconnected
	clientDisconnected := false
	go func() {
		<-c.Request.Context().Done()
		clientDisconnected = true
		cancel()
	}()

	collectionAddress := common.HexToAddress(collectionAddressStr)

	// Send initial progress
	step := 1
	total := 50
	if !sendProgressSafe(c, &clientDisconnected, "progress", "Starting analysis...", step, total, "") {
		return
	}
	step++

	// Get current block
	currentBlock, err := ethClient.getBlockNumber(ctx)
	if err != nil {
		sendProgressSafe(c, &clientDisconnected, "error", err.Error(), step, total, "")
		return
	}

	if !sendProgressSafe(c, &clientDisconnected, "progress", fmt.Sprintf("Connected to blockchain. Current block: %d", currentBlock), step, total, "") {
		return
	}
	step++

	// Calculate historical blocks
	secondsIn6Months := 6 * 30 * 24 * 60 * 60
	secondsIn1Year := 12 * 30 * 24 * 60 * 60
	blocksIn6Months := uint64(secondsIn6Months / config.AvgBlockTimeSeconds)
	blocksIn1Year := uint64(secondsIn1Year / config.AvgBlockTimeSeconds)

	var block6mAgo, block1yAgo uint64
	if currentBlock > blocksIn6Months {
		block6mAgo = currentBlock - blocksIn6Months
	}
	if currentBlock > blocksIn1Year {
		block1yAgo = currentBlock - blocksIn1Year
	}

	targetBlocks := map[string]uint64{
		"-1 Year":   block1yAgo,
		"-6 Months": block6mAgo,
		"Now":       currentBlock,
	}

	if !sendProgressSafe(c, &clientDisconnected, "progress", fmt.Sprintf("Calculated historical blocks: 1yr=%d, 6mo=%d", block1yAgo, block6mAgo), step, total, "") {
		return
	}
	step += 2

	// Process blocks with progress updates
	results := make(map[string]*BlockResult)
	var stepMutex sync.Mutex

	for label, blockNum := range targetBlocks {
		if clientDisconnected {
			return
		}

		if !sendProgressSafe(c, &clientDisconnected, "progress", fmt.Sprintf("Starting analysis for %s (block %d)...", label, blockNum), step, total, "") {
			return
		}
		stepMutex.Lock()
		step++
		stepMutex.Unlock()

		progressChan := make(chan string, 100)
		var progressWg sync.WaitGroup
		progressWg.Add(1)

		go func() {
			defer progressWg.Done()
			for {
				select {
				case msg, ok := <-progressChan:
					if !ok {
						return
					}
					if clientDisconnected {
						return
					}
					stepMutex.Lock()
					currentStep := step
					step++
					stepMutex.Unlock()
					if !sendProgressSafe(c, &clientDisconnected, "progress", fmt.Sprintf("[%s] %s", label, msg), currentStep, total, "") {
						return
					}
				case <-ctx.Done():
					return
				}
			}
		}()

		result, err := ethClient.fetchDataAtBlock(ctx, collectionAddress, blockNum, progressChan)
		close(progressChan)
		progressWg.Wait() // Wait for progress goroutine to finish

		if clientDisconnected {
			return
		}

		if err != nil {
			result = &BlockResult{
				Label:   label,
				Block:   blockNum,
				Success: false,
				Errors:  []string{fmt.Sprintf("Error: %v", err)},
			}
		}
		result.Label = label
		results[label] = result

		if !sendProgressSafe(c, &clientDisconnected, "progress", fmt.Sprintf("Completed %s: %d owners, %s ETH", label, result.Owners, result.BalanceETH.String()), step, total, "") {
			return
		}
		stepMutex.Lock()
		step += 5
		stepMutex.Unlock()
	}

	if clientDisconnected {
		return
	}

	// Generate final results
	if !sendProgressSafe(c, &clientDisconnected, "progress", "Generating chart and final results...", step, total, "") {
		return
	}
	html := generateResultsHTML(results)

	sendProgressSafe(c, &clientDisconnected, "complete", "Analysis complete!", total, total, html)
}

func sendProgressSafe(c *gin.Context, clientDisconnected *bool, msgType, message string, step, total int, html string) bool {
	if *clientDisconnected {
		return false
	}

	update := ProgressUpdate{
		Type:    msgType,
		Message: message,
		Step:    step,
		Total:   total,
		HTML:    html,
	}

	data, _ := json.Marshal(update)
	
	// Check if client is still connected before writing
	select {
	case <-c.Request.Context().Done():
		*clientDisconnected = true
		return false
	default:
	}

	_, err := c.Writer.Write([]byte(fmt.Sprintf("data: %s\n\n", data)))
	if err != nil {
		log.Printf("Error writing to client (client likely disconnected): %v", err)
		*clientDisconnected = true
		return false
	}

	if flusher, ok := c.Writer.(http.Flusher); ok {
		flusher.Flush()
	}

	return true
}

func generateResultsHTML(results map[string]*BlockResult) string {
	html := `<div id="results">`
	html += `<h3>Summary Over Time</h3>`
	html += `<table border="1" style="width:100%; border-collapse: collapse; margin-bottom: 1em;">`
	html += `<tr><th>Time Point</th><th>Block</th><th>Unique Owners</th><th>Total Powder (ETH)</th><th>Avg Powder (ETH)</th><th>Checked Tokens</th><th>Status</th></tr>`

	orderedLabels := []string{"-1 Year", "-6 Months", "Now"}
	timeLabels := []string{}
	powderValues := []float64{}

	for _, label := range orderedLabels {
		if result, exists := results[label]; exists {
			status := "Success"
			if !result.Success {
				status = `<span class="error">Failed</span>`
			}

			avgPowder := decimal.Zero
			if result.Owners > 0 {
				avgPowder = result.BalanceETH.Div(decimal.NewFromInt(int64(result.Owners)))
			}

			html += fmt.Sprintf(`<tr><td>%s</td><td>%d</td><td>%d</td><td>%s</td><td>%s</td><td>%d</td><td>%s</td></tr>`,
				label, result.Block, result.Owners, result.BalanceETH.StringFixed(4), avgPowder.StringFixed(4), result.CheckedTokens, status)

			if result.Success {
				timeLabels = append(timeLabels, label)
				avgFloat, _ := avgPowder.Float64()
				powderValues = append(powderValues, avgFloat)
			}
		}
	}

	html += `</table>`
	html += `<h3>Average Owner Powder Trend</h3>`

	// Generate chart if we have enough data
	if len(timeLabels) > 1 {
		chartID := fmt.Sprintf("chart-%d", time.Now().Unix())
		timeLabelsJSON, _ := json.Marshal(timeLabels)
		powderValuesJSON, _ := json.Marshal(powderValues)

		html += fmt.Sprintf(`
		<div id="%s" style="width: 100%%; max-width: 800px; height: 400px; margin: 0 auto;"></div>
		<script>
			var plotData = [{
				x: %s,
				y: %s,
				type: 'scatter',
				mode: 'lines+markers',
				name: 'Avg ETH per Owner'
			}];
			var layout = {
				title: 'Average Owner Powder (ETH) Over Time',
				xaxis: { title: 'Time Point' },
				yaxis: { title: 'Avg ETH per Owner', rangemode: 'tozero' },
				margin: { l: 40, r: 20, t: 40, b: 30 }
			};
			Plotly.newPlot('%s', plotData, layout);
		</script>
		`, chartID, timeLabelsJSON, powderValuesJSON, chartID)
	} else {
		html += `<p>Not enough data points to generate graph.</p>`
	}

	html += `</div>`
	return html
}

func main() {
	// Load configuration
	config = loadConfig()

	// Initialize Ethereum client
	var err error
	ethClient, err = newEthereumClient(config)
	if err != nil {
		log.Fatalf("Failed to initialize Ethereum client: %v", err)
	}

	// Test connection
	ctx := context.Background()
	blockNumber, err := ethClient.getBlockNumber(ctx)
	if err != nil {
		log.Fatalf("Failed to get block number: %v", err)
	}
	log.Printf("Successfully connected to %s. Current block: %d", config.NodeURL, blockNumber)

	// Setup Gin router
	gin.SetMode(gin.ReleaseMode)
	r := gin.Default()

	// CORS middleware
	r.Use(cors.New(cors.Config{
		AllowOrigins:     []string{"*"},
		AllowMethods:     []string{"GET", "POST", "PUT", "DELETE", "OPTIONS"},
		AllowHeaders:     []string{"*"},
		ExposeHeaders:    []string{"*"},
		AllowCredentials: true,
	}))

	// Routes
	r.GET("/node-status", nodeStatusHandler)
	r.GET("/", indexHandler)
	r.POST("/get-owners-powder", getOwnersPowderHandler)
	r.GET("/progress-stream", progressStreamHandler)

	// Start server
	port := ":" + config.Port
	log.Printf("Starting server on port %s", port)
	if err := r.Run(port); err != nil {
		log.Fatalf("Failed to start server: %v", err)
	}
}