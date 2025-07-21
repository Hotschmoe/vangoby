import os
import time
import datetime
import asyncio
import aiohttp
import concurrent.futures
from flask import Flask, request, render_template_string, Response, stream_with_context
from web3 import Web3
from decimal import Decimal
import plotly.graph_objects as go
import json
import requests
import threading
from functools import lru_cache
import hashlib

app = Flask(__name__)

# --- Configuration ---
NODE_URL = 'http://192.168.10.8:8545'
REQUEST_TIMEOUT = 240 
MAX_TOKENS_TO_CHECK = 10000
AVG_BLOCK_TIME_SECONDS = 12
OWNER_BATCH_SIZE = 50  # Increased from 25
BALANCE_BATCH_SIZE = 100  # Increased from 50
CONCURRENT_BATCHES = 8  # Number of concurrent batch requests

# Increased connection pool for better HTTP performance
session = requests.Session()
session.mount('http://', requests.adapters.HTTPAdapter(
    pool_maxsize=50,  # Increased
    pool_connections=50,  # Increased
    max_retries=3
))

# Minimal ERC721 ABI for totalSupply and ownerOf
MINIMAL_ERC721_ABI = [
    {
        "constant": True,
        "inputs": [],
        "name": "totalSupply",
        "outputs": [{"name": "", "type": "uint256"}],
        "payable": False,
        "stateMutability": "view",
        "type": "function",
    },
    {
        "constant": True,
        "inputs": [{"name": "tokenId", "type": "uint256"}],
        "name": "ownerOf",
        "outputs": [{"name": "", "type": "address"}],
        "payable": False,
        "stateMutability": "view",
        "type": "function",
    },
]

# --- Web3 Connection with improved HTTP settings ---
w3 = None
try:
    provider = Web3.HTTPProvider(
        NODE_URL, 
        session=session,
        request_kwargs={
            'timeout': REQUEST_TIMEOUT
        }
    )
    w3 = Web3(provider)
    block_number = w3.eth.block_number
    print(f"Successfully connected to {NODE_URL}. Current block: {block_number}")
except Exception as e:
    print(f"Failed to connect or initialize Web3 ({NODE_URL}). Error: {e}")

# --- Cache for token ownership data ---
owner_cache = {}
balance_cache = {}  # Cache for balance data
contract_cache = {}  # Cache for contract instances

# Cache key generator
def cache_key(contract_address, block, token_range=None):
    """Generate cache key for contract data"""
    key_data = f"{contract_address}_{block}"
    if token_range:
        key_data += f"_{token_range[0]}_{token_range[1]}"
    return hashlib.md5(key_data.encode()).hexdigest()

# --- Async batch API request helper functions ---
async def async_batch_get_owners(contract_instance, token_ids, block_identifier):
    """Get multiple owners in a single async RPC batch request"""
    # Check cache first
    cache_k = cache_key(contract_instance.address, block_identifier, (min(token_ids), max(token_ids)))
    if cache_k in owner_cache:
        return owner_cache[cache_k]
    
    batch = []
    
    # Prepare batch calls
    for token_id in token_ids:
        try:
            tx_data = contract_instance.functions.ownerOf(token_id).build_transaction({
                'chainId': 1, 'gas': 100000, 'gasPrice': w3.to_wei('1', 'gwei'), 'nonce': 0
            })
            encoded_data = tx_data['data']
            
            if encoded_data:
                batch.append({
                    'jsonrpc': '2.0',
                    'method': 'eth_call',
                    'params': [{
                        'to': contract_instance.address,
                        'data': encoded_data
                    }, hex(block_identifier) if isinstance(block_identifier, int) else block_identifier],
                    'id': token_id
                })
        except Exception as e:
            print(f"Error encoding data for token {token_id}: {e}")
            continue
    
    if not batch:
        return set()
    
    # Send async batch request
    timeout = aiohttp.ClientTimeout(total=REQUEST_TIMEOUT)
    async with aiohttp.ClientSession(timeout=timeout) as sess:
        async with sess.post(NODE_URL, json=batch) as response:
            results = await response.json()
    
    # Process results
    owners = set()
    for result in results:
        if 'result' in result and result['result']:
            owner_hex = result['result']
            if len(owner_hex) >= 42:
                owner = w3.to_checksum_address('0x' + owner_hex[-40:])
                owners.add(owner)
    
    # Cache result
    owner_cache[cache_k] = owners
    return owners

async def async_batch_get_balances(owner_addresses, block_identifier, batch_size=None):
    """Get balances for multiple addresses in async batches"""
    if batch_size is None:
        batch_size = BALANCE_BATCH_SIZE
        
    # Check cache first
    sorted_addresses = tuple(sorted(owner_addresses))
    cache_k = cache_key('balances', block_identifier, (hash(sorted_addresses),))
    if cache_k in balance_cache:
        return balance_cache[cache_k]
        
    total_balance_wei = 0
    num_addresses = len(owner_addresses)
    
    if num_addresses == 0:
        return 0
    
    # Process in concurrent batches
    timeout = aiohttp.ClientTimeout(total=REQUEST_TIMEOUT)
    async with aiohttp.ClientSession(timeout=timeout) as sess:
        semaphore = asyncio.Semaphore(CONCURRENT_BATCHES)  # Limit concurrent requests
        
        async def process_batch(start_idx, end_idx):
            async with semaphore:
                batch_addresses = owner_addresses[start_idx:end_idx]
                if not batch_addresses:
                    return 0
                    
                batch = []
                for j, address in enumerate(batch_addresses):
                    batch.append({
                        'jsonrpc': '2.0',
                        'method': 'eth_getBalance',
                        'params': [address, hex(block_identifier) if isinstance(block_identifier, int) else block_identifier],
                        'id': start_idx + j
                    })
                
                try:
                    async with sess.post(NODE_URL, json=batch) as response:
                        results = await response.json()
                        
                    batch_total = 0
                    for result in results:
                        if 'result' in result and result['result']:
                            balance = int(result['result'], 16)
                            batch_total += balance
                        elif 'error' in result:
                            print(f"Balance error: {result['error']}")
                    return batch_total
                except Exception as e:
                    print(f"Batch balance request failed: {e}")
                    return 0
        
        # Create tasks for all batches
        tasks = []
        for i in range(0, num_addresses, batch_size):
            batch_end = min(i + batch_size, num_addresses)
            tasks.append(process_batch(i, batch_end))
        
        # Execute all batches concurrently
        batch_results = await asyncio.gather(*tasks, return_exceptions=True)
        
        for result in batch_results:
            if isinstance(result, int):
                total_balance_wei += result
            else:
                print(f"Batch processing error: {result}")
    
    # Cache result
    balance_cache[cache_k] = total_balance_wei
    return total_balance_wei

# Sync wrappers for backward compatibility
def batch_get_owners(w3_instance, contract_instance, token_ids, block_identifier):
    """Sync wrapper for async batch_get_owners"""
    try:
        loop = asyncio.get_event_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
    
    return loop.run_until_complete(
        async_batch_get_owners(contract_instance, token_ids, block_identifier)
    )

def batch_get_balances(w3_instance, owner_addresses, block_identifier, batch_size=None):
    """Sync wrapper for async batch_get_balances"""
    if batch_size is None:
        batch_size = BALANCE_BATCH_SIZE
        
    try:
        loop = asyncio.get_event_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
    
    return loop.run_until_complete(
        async_batch_get_balances(owner_addresses, block_identifier, batch_size)
    )

# --- Optimized helper function for fetching data ---
def fetch_data_at_block(w3_instance, contract_instance, block_identifier):
    """Fetches unique owners and their total balance at a specific block."""
    start_time = time.time()
    print(f"Fetching data for block: {block_identifier}...")
    fetch_errors = []
    ownerof_duration = 0
    balance_duration = 0
    
    try:
        # Get total supply at the specified block
        total_supply = contract_instance.functions.totalSupply().call(block_identifier=block_identifier)
        tokens_to_check = min(total_supply, MAX_TOKENS_TO_CHECK)
        print(f"  [Block {block_identifier}] Total supply: {total_supply}. Checking first {tokens_to_check} tokens.")

        # --- Batch OwnerOf --- 
        start_ownerof = time.time()
        
        # Process in optimized batches
        batch_size = OWNER_BATCH_SIZE
        unique_owners = set()
        checked_token_count = 0
        
        for i in range(0, tokens_to_check, batch_size):
            batch_end = min(i + batch_size, tokens_to_check)
            token_batch = list(range(i, batch_end))
            checked_token_count += len(token_batch)
            
            try:
                # Use batched request
                batch_owners = batch_get_owners(w3_instance, contract_instance, token_batch, block_identifier)
                unique_owners.update(batch_owners)
                
                if i > 0 and i % 100 == 0:  # Reduced logging frequency
                    print(f"  [Block {block_identifier}] Checked ownerOf up to token ID: {i}")
            except Exception as e:
                err_msg = f"Err batch_get_owners(IDs {i}-{batch_end}, Block {block_identifier}): {str(e)[:100]}"
                if len(fetch_errors) < 5:
                    fetch_errors.append(err_msg)
                print(err_msg)
        
        ownerof_duration = time.time() - start_ownerof
        print(f"  [Block {block_identifier}] Found {len(unique_owners)} owners in {ownerof_duration:.2f}s.")

        # --- Batch Balance --- 
        start_balance = time.time()
        try:
            # Get all balances using optimized async batching
            total_balance_wei = batch_get_balances(w3_instance, list(unique_owners), block_identifier)
        except Exception as e:
            err_msg = f"Err batch_get_balances(Block {block_identifier}): {str(e)[:100]}"
            print(err_msg)
            if len(fetch_errors) < 5:
                fetch_errors.append(err_msg)
            total_balance_wei = 0
        
        balance_duration = time.time() - start_balance
        print(f"  [Block {block_identifier}] Checked balances in {balance_duration:.2f}s.")
        
        total_balance_eth = w3_instance.from_wei(total_balance_wei, 'ether')
        
        print(f"Finished fetching data for block {block_identifier}. Total time: {time.time() - start_time:.2f}s")
        return {
            'owners': len(unique_owners),
            'balance_eth': total_balance_eth,
            'checked_tokens': checked_token_count,
            'errors': fetch_errors,
            'ownerof_duration': ownerof_duration,
            'balance_duration': balance_duration,
            'block': block_identifier,
            'success': True
        }

    except Exception as e:
        print(f"Error fetching data for block {block_identifier}: {e}")
        fetch_errors.append(f"Major error fetching data for block {block_identifier}: {str(e)[:150]}")
        return {
            'owners': 0,
            'balance_eth': Decimal(0),
            'checked_tokens': 0,
            'errors': fetch_errors,
            'ownerof_duration': ownerof_duration,
            'balance_duration': balance_duration,
            'block': block_identifier,
            'success': False
        }

# --- Parallel execution of block data fetching ---
def fetch_all_blocks_in_parallel(w3_instance, contract_instance, target_blocks):
    """Fetch data for multiple blocks in parallel using async processing"""
    results_data = []
    
    # Use async processing instead of thread pool for better performance
    try:
        loop = asyncio.get_event_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
    
    async def fetch_all_async():
        tasks = []
        for label, block_num in target_blocks.items():
            task = asyncio.create_task(
                asyncio.to_thread(fetch_data_at_block, w3_instance, contract_instance, block_num)
            )
            tasks.append((task, label, block_num))
        
        results = []
        for task, label, block_num in tasks:
            try:
                result = await task
                results.append({
                    'label': label,
                    'block': block_num,
                    'data': result
                })
            except Exception as e:
                print(f"Error in async fetch for '{label}' ({block_num}): {e}")
                results.append({
                    'label': label,
                    'block': block_num,
                    'data': {
                        'success': False,
                        'errors': [f"Error: {str(e)}"],
                        'owners': 0,
                        'balance_eth': Decimal(0),
                        'checked_tokens': 0,
                        'ownerof_duration': 0,
                        'balance_duration': 0,
                        'block': block_num
                    }
                })
        return results
    
    results_data = loop.run_until_complete(fetch_all_async())
    
    # Calculate total fetch duration from individual results
    total_fetch_duration = sum(
        res['data'].get('ownerof_duration', 0) + res['data'].get('balance_duration', 0)
        for res in results_data if res['data'].get('success', False)
    )
    
    return results_data, total_fetch_duration

# --- Frontend Route ---
@app.route('/')
def index():
    try:
        with open('index.html', 'r') as f:
            return render_template_string(f.read())
    except FileNotFoundError:
        return "Error: index.html not found.", 404
    except Exception as e:
        print(f"Error reading index.html: {e}")
        return "Internal Server Error", 500

# --- Optimized HTMX Backend Route ---
@app.route('/get-owners-powder', methods=['POST'])
def get_owners_powder():
    start_time_total = time.time()

    # Check connection before proceeding
    if not w3:
        return '<div id="results" class="error">Error: Web3 not initialized. Check backend logs.</div>'
    try:
        w3.eth.block_number 
    except Exception as e:
        print(f"Error checking connection inside route: {e}")
        return '<div id="results" class="error">Error: Ethereum node connection lost. Please check backend logs.</div>'

    collection_address_str = request.form.get('collection_address')
    if not collection_address_str:
        return '<div id="results" class="error">Error: Collection address not provided.</div>'

    try:
        collection_address = w3.to_checksum_address(collection_address_str)
        
        # Use cached contract instance
        if collection_address not in contract_cache:
            contract_cache[collection_address] = w3.eth.contract(address=collection_address, abi=MINIMAL_ERC721_ABI)
        contract = contract_cache[collection_address]
        
    except ValueError:
         return f'<div id="results" class="error">Error: Invalid collection address format: {collection_address_str}</div>'
    except Exception as e:
        print(f"Error creating contract object: {e}")
        return '<div id="results" class="error">Error: Could not interact with the provided address. Is it a valid contract?</div>'

    # --- Calculate Past Block Numbers --- 
    print(f"Current Block: {w3.eth.block_number}")
    seconds_in_6_months = 6 * 30 * 24 * 60 * 60
    seconds_in_1_year = 12 * 30 * 24 * 60 * 60
    blocks_in_6_months = seconds_in_6_months // AVG_BLOCK_TIME_SECONDS
    blocks_in_1_year = seconds_in_1_year // AVG_BLOCK_TIME_SECONDS
    
    block_6m_ago = max(0, w3.eth.block_number - blocks_in_6_months)
    block_1y_ago = max(0, w3.eth.block_number - blocks_in_1_year)
    
    target_blocks = {
        '-1 Year': block_1y_ago,
        '-6 Months': block_6m_ago,
        'Now': w3.eth.block_number
    }
    
    # --- Fetch All Blocks in Parallel ---
    results_data, total_fetch_duration = fetch_all_blocks_in_parallel(
        w3, contract, target_blocks
    )
    
    # --- Process Errors ---
    all_errors = []
    for item in results_data:
        if item['data']['errors']:
            all_errors.extend([f"[{item['label']} @{item['block']}] {err}" for err in item['data']['errors']])
            
    # --- Prepare Data for Graphing --- 
    time_labels = []
    powder_per_owner_values = []
    successful_fetches = 0
    
    for item in results_data:
        label = item['label']
        data = item['data']
        if data['success']:
            successful_fetches += 1
            time_labels.append(label)
            num_owners = data['owners']
            balance = data['balance_eth']
            # Avoid division by zero
            powder_per_owner = (balance / num_owners) if num_owners > 0 else Decimal(0)
            powder_per_owner_values.append(float(powder_per_owner))
        else:
            print(f"Skipping failed data point for '{label}' in graph.")
            
    # --- Generate Graph (only if we have data) --- 
    graph_html = "<p>Not enough data points to generate graph.</p>"
    if len(time_labels) > 1:
        try:
            fig = go.Figure(data=go.Scatter(x=time_labels, y=powder_per_owner_values, mode='lines+markers'))
            fig.update_layout(
                title='Average Owner Powder (ETH) Over Time',
                xaxis_title='Time Point',
                yaxis_title='Avg ETH per Owner',
                margin=dict(l=40, r=20, t=40, b=30)
            )
            graph_html = fig.to_html(full_html=False, include_plotlyjs=False)
            print("Successfully generated Plotly graph HTML fragment.")
        except Exception as e:
            print(f"Error generating Plotly graph: {e}")
            graph_html = f'<p class="error">Error generating graph: {e}</p>'
    elif len(time_labels) == 1:
         graph_html = f"<p>Only got data for one time point ({time_labels[0]}). Cannot draw a line graph.</p>"

    # --- Construct HTML Response --- 
    response_html = '<div id="results">'
    response_html += '<h3>Summary Over Time</h3>'
    response_html += '<table border="1" style="width:100%; border-collapse: collapse; margin-bottom: 1em;">'
    response_html += '<tr><th>Time Point</th><th>Block</th><th>Unique Owners</th><th>Total Powder (ETH)</th><th>Avg Powder (ETH)</th><th>Checked Tokens</th><th>Status</th></tr>'
    
    total_owners = 0
    total_balance = Decimal(0)
    total_checked = 0
    
    for item in results_data:
        label = item['label']
        block = item['block']
        data = item['data']
        status = "Success" if data['success'] else "<span class='error'>Failed</span>"
        owners = data['owners']
        balance = data['balance_eth']
        checked = data['checked_tokens']
        avg_powder = (balance / owners) if owners > 0 else Decimal(0)
        
        total_owners += owners
        total_balance += balance
        total_checked += checked
        
        response_html += f'<tr><td>{label}</td><td>{block}</td><td>{owners}</td><td>{balance:.4f}</td><td>{avg_powder:.4f}</td><td>{checked}</td><td>{status}</td></tr>'
    
    response_html += '</table>'
    
    response_html += '<h3>Average Owner Powder Trend</h3>'
    response_html += graph_html
    
    # Add warnings/errors if any occurred
    any_token_limit_hit = any(res['data']['checked_tokens'] == MAX_TOKENS_TO_CHECK for res in results_data if res['data']['success'])
    if any_token_limit_hit:
        response_html += f'<p class="warning">Warning: MAX_TOKENS_TO_CHECK ({MAX_TOKENS_TO_CHECK}) limit was hit for one or more time points. Results may be incomplete.</p>'
        
    if all_errors:
        response_html += '<p class="error">Encountered errors during data fetching:</p><ul>'
        for err in all_errors[:10]:
            response_html += f'<li>{err}</li>'
        if len(all_errors) > 10:
            response_html += f'<li>... ({len(all_errors) - 10} more errors not shown)</li>'
        response_html += '</ul>'
        
    response_html += '</div>'

    # --- Timing & Return --- 
    end_time_total = time.time()
    total_duration = end_time_total - start_time_total
    print(f"Total request time for {collection_address_str}: {total_duration:.2f} seconds")
    print(f"  - Total data fetch duration across blocks: {total_fetch_duration:.2f}s")
    
    return response_html

# --- Server-Sent Events for Progressive Loading ---
@app.route('/sse-owners-powder')
def sse_owners_powder():
    """Stream results as they come in using Server-Sent Events"""
    collection_address_str = request.args.get('collection_address')
    if not collection_address_str or not w3:
        return Response("data: {\"error\": \"Invalid parameters or Web3 not initialized\"}\\n\\n",
                        mimetype="text/event-stream")
    
    def generate():
        try:
            collection_address = w3.to_checksum_address(collection_address_str)
            contract = w3.eth.contract(address=collection_address, abi=MINIMAL_ERC721_ABI)
            
            # Calculate blocks as in the main function
            current_block = w3.eth.block_number
            seconds_in_6_months = 6 * 30 * 24 * 60 * 60
            seconds_in_1_year = 12 * 30 * 24 * 60 * 60
            blocks_in_6_months = seconds_in_6_months // AVG_BLOCK_TIME_SECONDS
            blocks_in_1_year = seconds_in_1_year // AVG_BLOCK_TIME_SECONDS
            
            block_6m_ago = max(0, current_block - blocks_in_6_months)
            block_1y_ago = max(0, current_block - blocks_in_1_year)
            
            target_blocks = {
                '-1 Year': block_1y_ago,
                '-6 Months': block_6m_ago,
                'Now': current_block
            }
            
            # Process blocks and stream results as they come in
            completed_blocks = 0
            results = {}
            
            # Process one block at a time and send updates
            for label, block_num in target_blocks.items():
                result = fetch_data_at_block(w3, contract, block_num)
                completed_blocks += 1
                
                results[label] = {
                    'block': block_num,
                    'data': result
                }
                
                # Send partial results
                yield f"data: {json.dumps({'label': label, 'results': results, 'complete': completed_blocks == len(target_blocks)})}\\n\\n"
                
            # Final message to indicate completion
            yield f"data: {json.dumps({'complete': True, 'results': results})}\\n\\n"
            
        except Exception as e:
            yield f"data: {json.dumps({'error': str(e)})}\\n\\n"
    
    return Response(stream_with_context(generate()), mimetype="text/event-stream")

# --- Run Flask App ---
if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5001)