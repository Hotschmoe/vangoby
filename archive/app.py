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
import uuid

app = Flask(__name__)

# --- Configuration ---
NODE_URL = 'http://192.168.10.8:8545'
REQUEST_TIMEOUT = 240 
MAX_TOKENS_TO_CHECK = 11000
AVG_BLOCK_TIME_SECONDS = 12
# This are set by Erigon Node, below are the default values. You can chagne them in the Erigon RPC
OWNER_BATCH_SIZE = 100
BALANCE_BATCH_SIZE = 100
CONCURRENT_BATCHES = 10
MAX_CONCURRENT_CONNECTIONS = 50

# Increased connection pool for better HTTP performance
session = requests.Session()
session.mount('http://', requests.adapters.HTTPAdapter(
    pool_maxsize=50,
    pool_connections=50,
    max_retries=3
))

# Global aiohttp session for async requests
async_session = None

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

# Cache key generator
def cache_key(contract_address, block, token_range=None):
    """Generate cache key for contract data"""
    key_data = f"{contract_address}_{block}"
    if token_range:
        key_data += f"_{token_range[0]}_{token_range[1]}"
    return hashlib.md5(key_data.encode()).hexdigest()

# --- Async HTTP session management ---
async def get_async_session():
    global async_session
    if async_session is None:
        connector = aiohttp.TCPConnector(
            limit=MAX_CONCURRENT_CONNECTIONS,
            limit_per_host=MAX_CONCURRENT_CONNECTIONS,
            ttl_dns_cache=300,
            use_dns_cache=True,
        )
        timeout = aiohttp.ClientTimeout(total=REQUEST_TIMEOUT)
        async_session = aiohttp.ClientSession(
            connector=connector,
            timeout=timeout
        )
    return async_session

async def close_async_session():
    global async_session
    if async_session:
        await async_session.close()
        async_session = None

# --- Async batch API request helper functions ---
async def async_batch_get_owners(w3_instance, contract_instance, token_ids, block_identifier):
    """Get multiple owners in a single async RPC batch request"""
    batch = []

    # Prepare batch calls
    for token_id in token_ids:
        try:
            tx_data = contract_instance.functions.ownerOf(token_id).build_transaction({
                'chainId': 1,
                'gas': 100000,
                'gasPrice': w3_instance.to_wei('1', 'gwei'),
                'nonce': 0
            })
            encoded_data = tx_data['data']
        except Exception as e:
            print(f"Error encoding data for token {token_id}: {e}")
            continue

        batch.append({
            'jsonrpc': '2.0',
            'method': 'eth_call',
            'params': [{
                'to': contract_instance.address,
                'data': encoded_data
            }, hex(block_identifier) if isinstance(block_identifier, int) else block_identifier],
            'id': token_id
        })

    # Send async batch request
    session = await get_async_session()
    async with session.post(NODE_URL, json=batch) as response:
        results = await response.json()
    
    # Process results
    owners = set()
    for result in results:
        if 'result' in result and result['result']:
            owner_hex = result['result']
            if len(owner_hex) >= 42:
                owner = w3_instance.to_checksum_address('0x' + owner_hex[-40:])
                owners.add(owner)
    
    return owners

async def async_batch_get_balances(w3_instance, owner_addresses, block_identifier, batch_size=200):
    """Get balances for multiple addresses in async batches"""
    total_balance_wei = 0
    num_addresses = len(owner_addresses)
    
    # Create batches
    batches = []
    for i in range(0, num_addresses, batch_size):
        batch_end = min(i + batch_size, num_addresses)
        address_batch = owner_addresses[i:batch_end]
        
        if not address_batch:
            continue

        batch = []
        for j, address in enumerate(address_batch):
            batch.append({
                'jsonrpc': '2.0',
                'method': 'eth_getBalance',
                'params': [address, hex(block_identifier) if isinstance(block_identifier, int) else block_identifier],
                'id': i + j
            })
        batches.append(batch)
    
    # Execute all batches concurrently
    session = await get_async_session()
    tasks = []
    
    async def process_batch(batch):
        try:
            async with session.post(NODE_URL, json=batch) as response:
                results = await response.json()
                batch_total = 0
                for result in results:
                    if 'result' in result and result['result']:
                        balance = int(result['result'], 16)
                        batch_total += balance
                    elif 'error' in result:
                        print(f"Error in balance RPC result: {result['error']}")
                return batch_total
        except Exception as e:
            print(f"Error processing balance batch: {e}")
            return 0
    
    for batch in batches:
        tasks.append(process_batch(batch))
    
    # Wait for all batches to complete
    batch_results = await asyncio.gather(*tasks, return_exceptions=True)
    
    for result in batch_results:
        if isinstance(result, int):
            total_balance_wei += result
        else:
            print(f"Batch processing error: {result}")
    
    return total_balance_wei

# --- Legacy sync functions (keeping for compatibility) ---
def batch_get_owners(w3_instance, contract_instance, token_ids, block_identifier):
    """Get multiple owners in a single RPC batch request"""
    batch = []

    # Prepare batch calls using build_transaction (for web3.py v4/v5 compatibility)
    for token_id in token_ids:
        # Build a dummy transaction dict just to get the data field
        # The 'from' address is irrelevant for eth_call but often needed by build_transaction
        try:
            tx_data = contract_instance.functions.ownerOf(token_id).build_transaction({
                'chainId': 1, # Dummy chain ID, ignored by eth_call
                'gas': 100000, # Dummy gas, ignored by eth_call
                'gasPrice': w3_instance.to_wei('1', 'gwei'), # Dummy gas price
                'nonce': 0 # Dummy nonce
            })
            encoded_data = tx_data['data']
        except AttributeError:
            # Fallback for potentially even older versions or different structure
            # This is less likely but provides a safety net
             try:
                 tx_data = contract_instance.functions.ownerOf(token_id).buildTransaction({
                    'chainId': 1, 'gas': 100000, 'gasPrice': w3_instance.to_wei('1', 'gwei'), 'nonce': 0
                 })
                 encoded_data = tx_data['data']
             except Exception as build_err:
                 print(f"Failed to encode data using build_transaction/buildTransaction for token {token_id}: {build_err}")
                 encoded_data = None # Skip this token if encoding fails
        except Exception as e:
             print(f"Unexpected error encoding data for token {token_id}: {e}")
             encoded_data = None # Skip this token if encoding fails

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

    # Send batch request
    response = session.post(
        NODE_URL,
        json=batch,
        timeout=REQUEST_TIMEOUT
    )
    
    # Process results
    results = response.json()
    owners = []
    
    for result in results:
        if 'result' in result and result['result']:
            # Extract address from result (last 20 bytes)
            owner_hex = result['result']
            if len(owner_hex) >= 42:  # Ensure we have enough data
                owner = w3_instance.to_checksum_address('0x' + owner_hex[-40:])
                owners.append(owner)
    
    return set(owners)

def batch_get_balances(w3_instance, owner_addresses, block_identifier, batch_size=None):
    """Get balances for multiple addresses in batches"""
    if batch_size is None:
        batch_size = BALANCE_BATCH_SIZE
    """Get balances for multiple addresses in batches"""
    total_balance_wei = 0
    num_addresses = len(owner_addresses)
    
    for i in range(0, num_addresses, batch_size):
        batch_end = min(i + batch_size, num_addresses)
        address_batch = owner_addresses[i:batch_end]
        
        if not address_batch: # Skip empty batches
            continue

        batch = []
        # Prepare batch calls for the current chunk
        for j, address in enumerate(address_batch):
            batch.append({
                'jsonrpc': '2.0',
                'method': 'eth_getBalance',
                'params': [address, hex(block_identifier) if isinstance(block_identifier, int) else block_identifier],
                'id': i + j # Ensure unique IDs across all batches if needed, though response matching doesn't strictly rely on it here
            })
        
        try:
            # Send batch request for the current chunk
            response = session.post(
                NODE_URL,
                json=batch,
                timeout=REQUEST_TIMEOUT
            )
            response.raise_for_status() # Raise HTTPError for bad responses (4xx or 5xx)
            
            # Process results for the current chunk
            results = response.json()
            
            # Debug: Check if results is a list as expected
            if not isinstance(results, list):
                print(f"  [Balance Batch {i//batch_size + 1}] Warning: Expected list but got {type(results)}: {results}")
                continue
            
            for result in results:
                if not isinstance(result, dict):
                    print(f"  [Balance Batch {i//batch_size + 1}] Warning: Expected dict but got {type(result)}: {result}")
                    continue
                    
                if 'result' in result and result['result']:
                    balance = int(result['result'], 16)  # Convert hex to int
                    total_balance_wei += balance
                elif 'error' in result:
                     # Log or handle specific errors if needed
                     print(f"  [Balance Batch {i//batch_size + 1}] Error in RPC result: {result['error']}")
                     
        except requests.exceptions.RequestException as e:
            print(f"  [Balance Batch {i//batch_size + 1}] HTTP request failed: {e}")
            # Decide how to handle failure: continue, retry, or raise?
            # For now, we'll just print and continue, resulting in potentially lower total balance
            continue 
        except json.JSONDecodeError as e:
            print(f"  [Balance Batch {i//batch_size + 1}] Failed to decode JSON response: {e}")
            continue
        except Exception as e:
             print(f"  [Balance Batch {i//batch_size + 1}] Unexpected error processing batch: {e}")
             continue

    return total_balance_wei

# --- Async optimized helper function for fetching data ---
async def async_fetch_data_at_block(w3_instance, contract_instance, block_identifier, progress_callback=None):
    """Async version - Fetches unique owners and their total balance at a specific block."""
    start_time = time.time()
    print(f"Async fetching data for block: {block_identifier}...")
    fetch_errors = []
    ownerof_duration = 0
    balance_duration = 0
    
    def send_progress(message):
        if progress_callback:
            progress_callback(message)
    
    try:
        # Get total supply at the specified block (with caching)
        send_progress(f"Getting total supply at block {block_identifier}...")
        supply_cache_key = get_cache_key_supply(contract_instance.address, block_identifier)
        if supply_cache_key in total_supply_cache:
            total_supply = total_supply_cache[supply_cache_key]
            print(f"Cache hit for total supply at block {block_identifier}")
        else:
            total_supply = contract_instance.functions.totalSupply().call(block_identifier=block_identifier)
            total_supply_cache[supply_cache_key] = total_supply
        tokens_to_check = min(total_supply, MAX_TOKENS_TO_CHECK)
        print(f"  [Block {block_identifier}] Total supply: {total_supply}. Checking first {tokens_to_check} tokens.")
        send_progress(f"Found {total_supply} tokens. Checking first {tokens_to_check}...")

        # --- Async Batch OwnerOf with larger concurrent batches --- 
        start_ownerof = time.time()
        send_progress(f"Fetching owners for {tokens_to_check} tokens...")
        
        # Process in larger concurrent batches
        batch_size = OWNER_BATCH_SIZE
        unique_owners = set()
        checked_token_count = 0
        total_batches = (tokens_to_check + batch_size - 1) // batch_size
        
        # Create all batches
        owner_tasks = []
        for i in range(0, tokens_to_check, batch_size):
            batch_end = min(i + batch_size, tokens_to_check)
            token_batch = list(range(i, batch_end))
            checked_token_count += len(token_batch)
            
            # Create async task for each batch
            task = async_batch_get_owners(w3_instance, contract_instance, token_batch, block_identifier)
            owner_tasks.append((task, i, batch_end))
        
        # Execute batches with controlled concurrency
        semaphore = asyncio.Semaphore(CONCURRENT_BATCHES)
        
        async def process_owner_batch(task, start_idx, end_idx):
            async with semaphore:
                batch_num = (start_idx // batch_size) + 1
                send_progress(f"Processing token batch {batch_num}/{total_batches} (tokens {start_idx}-{end_idx-1})...")
                try:
                    batch_owners = await task
                    return batch_owners
                except Exception as e:
                    err_msg = f"Err async_batch_get_owners(IDs {start_idx}-{end_idx}, Block {block_identifier}): {str(e)[:100]}"
                    if len(fetch_errors) < 5:
                        fetch_errors.append(err_msg)
                    print(err_msg)
                    send_progress(f"Error in batch {batch_num}: {str(e)[:50]}...")
                    return set()
        
        # Execute all owner batches concurrently
        owner_results = await asyncio.gather(*[
            process_owner_batch(task, start_idx, end_idx) 
            for task, start_idx, end_idx in owner_tasks
        ], return_exceptions=True)
        
        # Combine all owner results
        for result in owner_results:
            if isinstance(result, set):
                unique_owners.update(result)
            else:
                print(f"Owner batch error: {result}")
        
        ownerof_duration = time.time() - start_ownerof
        print(f"  [Block {block_identifier}] Found {len(unique_owners)} owners in {ownerof_duration:.2f}s.")
        send_progress(f"Found {len(unique_owners)} unique owners. Now fetching balances...")

        # --- Async Batch Balance --- 
        start_balance = time.time()
        try:
            send_progress(f"Calculating ETH balances for {len(unique_owners)} addresses...")
            total_balance_wei = await async_batch_get_balances(w3_instance, list(unique_owners), block_identifier, BALANCE_BATCH_SIZE)
        except Exception as e:
            err_msg = f"Err async_batch_get_balances(Block {block_identifier}): {str(e)[:100]}"
            print(err_msg)
            if len(fetch_errors) < 5:
                fetch_errors.append(err_msg)
            total_balance_wei = 0
            send_progress(f"Error fetching balances: {str(e)[:50]}...")
        
        balance_duration = time.time() - start_balance
        print(f"  [Block {block_identifier}] Checked balances in {balance_duration:.2f}s.")
        
        total_balance_eth = w3_instance.from_wei(total_balance_wei, 'ether')
        send_progress(f"Block {block_identifier} complete: {len(unique_owners)} owners, {float(total_balance_eth):.4f} ETH total")
        
        print(f"Finished async fetching data for block {block_identifier}. Total time: {time.time() - start_time:.2f}s")
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
        print(f"Error async fetching data for block {block_identifier}: {e}")
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

# --- Legacy sync function (keeping for compatibility) ---
def fetch_data_at_block(w3_instance, contract_instance, block_identifier, progress_callback=None):
    """Fetches unique owners and their total balance at a specific block."""
    start_time = time.time()
    print(f"Fetching data for block: {block_identifier}...")
    fetch_errors = []
    ownerof_duration = 0
    balance_duration = 0
    
    def send_progress(message):
        if progress_callback:
            progress_callback(message)
    
    try:
        # Get total supply at the specified block
        send_progress(f"Getting total supply at block {block_identifier}...")
        total_supply = contract_instance.functions.totalSupply().call(block_identifier=block_identifier)
        tokens_to_check = min(total_supply, MAX_TOKENS_TO_CHECK)
        print(f"  [Block {block_identifier}] Total supply: {total_supply}. Checking first {tokens_to_check} tokens.")
        send_progress(f"Found {total_supply} tokens. Checking first {tokens_to_check}...")

        # --- Batch OwnerOf --- 
        start_ownerof = time.time()
        send_progress(f"Fetching owners for {tokens_to_check} tokens...")
        
        # Process in smaller batches for reliable processing  
        batch_size = 50  # Conservative batch size for stability
        unique_owners = set()
        checked_token_count = 0
        total_batches = (tokens_to_check + batch_size - 1) // batch_size
        
        # Process multiple batches concurrently using ThreadPoolExecutor
        with concurrent.futures.ThreadPoolExecutor(max_workers=CONCURRENT_BATCHES) as executor:
            # Create batch tasks
            batch_tasks = []
            for i in range(0, tokens_to_check, batch_size):
                batch_end = min(i + batch_size, tokens_to_check)
                token_batch = list(range(i, batch_end))
                checked_token_count += len(token_batch)
                batch_num = (i // batch_size) + 1
                
                # Submit batch to thread pool
                future = executor.submit(batch_get_owners, w3_instance, contract_instance, token_batch, block_identifier)
                batch_tasks.append((future, batch_num, i, batch_end))
            
            # Process completed batches
            for future, batch_num, start_idx, end_idx in batch_tasks:
                send_progress(f"Processing token batch {batch_num}/{total_batches} (tokens {start_idx}-{end_idx-1})...")
                
                try:
                    batch_owners = future.result()
                    unique_owners.update(batch_owners)
                    
                    if start_idx > 0 and start_idx % 50 == 0:
                        print(f"  [Block {block_identifier}] Checked ownerOf up to token ID: {start_idx}")
                        send_progress(f"Found {len(unique_owners)} unique owners so far...")
                except Exception as e:
                    err_msg = f"Err batch_get_owners(IDs {start_idx}-{end_idx}, Block {block_identifier}): {str(e)[:100]}"
                    if len(fetch_errors) < 5:
                        fetch_errors.append(err_msg)
                    print(err_msg)
                    send_progress(f"Error in batch {batch_num}: {str(e)[:50]}...")
        
        ownerof_duration = time.time() - start_ownerof
        print(f"  [Block {block_identifier}] Found {len(unique_owners)} owners in {ownerof_duration:.2f}s.")
        send_progress(f"Found {len(unique_owners)} unique owners. Now fetching balances...")

        # --- Batch Balance --- 
        start_balance = time.time()
        try:
            # Get all balances with optimized batch size
            send_progress(f"Calculating ETH balances for {len(unique_owners)} addresses...")
            total_balance_wei = batch_get_balances(w3_instance, list(unique_owners), block_identifier, BALANCE_BATCH_SIZE)
        except Exception as e:
            err_msg = f"Err batch_get_balances(Block {block_identifier}): {str(e)[:100]}"
            print(err_msg)
            if len(fetch_errors) < 5:
                fetch_errors.append(err_msg)
            total_balance_wei = 0
            send_progress(f"Error fetching balances: {str(e)[:50]}...")
        
        balance_duration = time.time() - start_balance
        print(f"  [Block {block_identifier}] Checked balances in {balance_duration:.2f}s.")
        
        total_balance_eth = w3_instance.from_wei(total_balance_wei, 'ether')
        send_progress(f"Block {block_identifier} complete: {len(unique_owners)} owners, {float(total_balance_eth):.4f} ETH total")
        
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

# --- Async parallel execution of block data fetching ---
async def async_fetch_all_blocks_in_parallel(w3_instance, contract_instance, target_blocks):
    """Async version - Fetch data for multiple blocks in parallel"""
    start_time = time.time()
    results_data = []
    
    # Create tasks for all blocks
    tasks = []
    for label, block_num in target_blocks.items():
        task = async_fetch_data_at_block(w3_instance, contract_instance, block_num)
        tasks.append((task, label, block_num))
    
    # Execute all blocks concurrently
    results = await asyncio.gather(*[task for task, _, _ in tasks], return_exceptions=True)
    
    # Process results
    for i, (result, (_, label, block_num)) in enumerate(zip(results, tasks)):
        if isinstance(result, dict):
            results_data.append({
                'label': label,
                'block': block_num,
                'data': result
            })
            print(f"Async block fetch for '{label}' ({block_num}) completed")
        else:
            print(f"Error in async_fetch_all_blocks_in_parallel for '{label}' ({block_num}): {result}")
            results_data.append({
                'label': label,
                'block': block_num,
                'data': {
                    'success': False,
                    'errors': [f"Error: {str(result)}"],
                    'owners': 0,
                    'balance_eth': Decimal(0),
                    'checked_tokens': 0,
                    'ownerof_duration': 0,
                    'balance_duration': 0,
                    'block': block_num
                }
            })
    
    total_fetch_duration = time.time() - start_time
    print(f"All async block fetches completed in {total_fetch_duration:.2f}s")
    return results_data, total_fetch_duration

# --- Legacy sync function (keeping for compatibility) ---
def fetch_all_blocks_in_parallel(w3_instance, contract_instance, target_blocks):
    """Fetch data for multiple blocks in parallel using ThreadPoolExecutor"""
    results_data = []
    total_fetch_duration = 0
    
    with concurrent.futures.ThreadPoolExecutor(max_workers=len(target_blocks)) as executor:
        future_to_label = {
            executor.submit(fetch_data_at_block, w3_instance, contract_instance, block_num): (label, block_num) 
            for label, block_num in target_blocks.items()
        }
        
        for future in concurrent.futures.as_completed(future_to_label):
            label, block_num = future_to_label[future]
            fetch_start_time = time.time()
            
            try:
                result = future.result()
                fetch_duration = time.time() - fetch_start_time
                total_fetch_duration += fetch_duration
                
                print(f"Block fetch for '{label}' ({block_num}) took {fetch_duration:.2f}s")
                results_data.append({
                    'label': label,
                    'block': block_num,
                    'data': result
                })
            except Exception as e:
                print(f"Error in fetch_all_blocks_in_parallel for '{label}' ({block_num}): {e}")
                results_data.append({
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
    
    return results_data, total_fetch_duration

# --- Node Status Route ---
@app.route('/node-status')
def node_status():
    try:
        if not w3:
            return {'connected': False, 'error': 'Web3 not initialized'}
        
        block_number = w3.eth.block_number
        return {'connected': True, 'block_number': block_number}
    except Exception as e:
        return {'connected': False, 'error': str(e)}

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
        contract = w3.eth.contract(address=collection_address, abi=MINIMAL_ERC721_ABI)
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
    
    # --- Fetch All Blocks in Parallel (Sync Version - Known Working) ---
    results_data, total_fetch_duration = fetch_all_blocks_in_parallel(
        w3, contract, target_blocks
    )
    
    # --- Process Errors ---
    all_errors = []
    for item in results_data:
        if item['data']['errors']:
            all_errors.extend([f"[{item['label']} @{item['block']}] {err}" for err in item['data']['errors']])
            
    # --- Prepare Data for Graphing (in correct chronological order) --- 
    time_labels = []
    powder_per_owner_values = []
    successful_fetches = 0
    
    # Sort results in chronological order: oldest first
    ordered_labels = ['-1 Year', '-6 Months', 'Now']
    
    for label in ordered_labels:
        # Find the result for this label
        result_item = next((item for item in results_data if item['label'] == label), None)
        if result_item and result_item['data']['success']:
            successful_fetches += 1
            time_labels.append(label)
            data = result_item['data']
            num_owners = data['owners']
            balance = data['balance_eth']
            # Avoid division by zero
            powder_per_owner = (balance / num_owners) if num_owners > 0 else Decimal(0)
            powder_per_owner_values.append(float(powder_per_owner))
        elif result_item:
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
                yaxis=dict(rangemode='tozero'),
                margin=dict(l=40, r=20, t=40, b=30),
                width=800,
                height=400
            )
            
            # Generate HTML version with proper Plotly.js integration
            import uuid
            chart_id = f"chart-{uuid.uuid4().hex[:8]}"
            graph_html = f'''
            <div id="{chart_id}" style="width: 100%; max-width: 800px; height: 400px; margin: 0 auto;"></div>
            <script>
                var plotData = [{json.dumps({
                    'x': time_labels,
                    'y': powder_per_owner_values,
                    'type': 'scatter',
                    'mode': 'lines+markers',
                    'name': 'Avg ETH per Owner'
                })}];
                var layout = {{
                    title: 'Average Owner Powder (ETH) Over Time',
                    xaxis: {{ title: 'Time Point' }},
                    yaxis: {{ title: 'Avg ETH per Owner', rangemode: 'tozero' }},
                    margin: {{ l: 40, r: 20, t: 40, b: 30 }}
                }};
                Plotly.newPlot('{chart_id}', plotData, layout);
            </script>
            '''
            print("Generated Plotly graph as HTML.")
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
    
    # Display table rows in chronological order
    for label in ordered_labels:
        # Find the result for this label
        result_item = next((item for item in results_data if item['label'] == label), None)
        if result_item:
            block = result_item['block']
            data = result_item['data']
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
        return Response("data: {\"error\": \"Invalid parameters or Web3 not initialized\"}\n\n",
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
                yield f"data: {json.dumps({'label': label, 'results': results, 'complete': completed_blocks == len(target_blocks)})}\n\n"
                
            # Final message to indicate completion
            yield f"data: {json.dumps({'complete': True, 'results': results})}\n\n"
            
        except Exception as e:
            yield f"data: {json.dumps({'error': str(e)})}\n\n"
    
    return Response(stream_with_context(generate()), mimetype="text/event-stream")

# --- Progress Streaming Endpoint ---
@app.route('/progress-stream')
def progress_stream():
    """Stream progress updates for queries using Server-Sent Events"""
    collection_address_str = request.args.get('collection_address')
    if not collection_address_str or not w3:
        return Response("data: {\"error\": \"Invalid parameters or Web3 not initialized\"}\n\n",
                        mimetype="text/event-stream")
    
    def generate():
        try:
            step = 1
            total = 50  # More granular progress
            
            yield f"data: {json.dumps({'type': 'progress', 'message': 'Starting analysis...', 'step': step, 'total': total})}\n\n"
            step += 1
            
            collection_address = w3.to_checksum_address(collection_address_str)
            contract = w3.eth.contract(address=collection_address, abi=MINIMAL_ERC721_ABI)
            
            # Calculate blocks
            current_block = w3.eth.block_number
            message = f'Connected to blockchain. Current block: {current_block}'
            yield f"data: {json.dumps({'type': 'progress', 'message': message, 'step': step, 'total': total})}\n\n"
            step += 1
            
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
            
            message = f'Calculated historical blocks: 1yr={block_1y_ago}, 6mo={block_6m_ago}'
            yield f"data: {json.dumps({'type': 'progress', 'message': message, 'step': step, 'total': total})}\n\n"
            step += 2
            
            # Process blocks and stream progress
            results_data = []
            
            for label, block_num in target_blocks.items():
                message = f'Starting analysis for {label} (block {block_num})...'
                yield f"data: {json.dumps({'type': 'progress', 'message': message, 'step': step, 'total': total})}\n\n"
                step += 1
                
                # Store progress messages to yield them
                progress_messages = []
                
                def progress_callback(msg):
                    progress_messages.append(msg)
                
                result = fetch_data_at_block(w3, contract, block_num, progress_callback)
                
                # Send all progress messages that were collected
                for msg in progress_messages:
                    yield f"data: {json.dumps({'type': 'progress', 'message': f'[{label}] {msg}', 'step': step, 'total': total})}\n\n"
                    step += 1
                
                results_data.append({
                    'label': label,
                    'block': block_num,
                    'data': result
                })
                
                message = f'Completed {label}: {result["owners"]} owners, {float(result["balance_eth"]):.4f} ETH'
                yield f"data: {json.dumps({'type': 'progress', 'message': message, 'step': step, 'total': total})}\n\n"
                step += 5
            
            # Generate final results
            yield f"data: {json.dumps({'type': 'progress', 'message': 'Generating chart and final results...', 'step': step, 'total': total})}\n\n"
            step += 2
            
            # Create the same HTML response as the main endpoint
            response_html = '<div id="results">'
            response_html += '<h3>Summary Over Time</h3>'
            response_html += '<table border="1" style="width:100%; border-collapse: collapse; margin-bottom: 1em;">'
            response_html += '<tr><th>Time Point</th><th>Block</th><th>Unique Owners</th><th>Total Powder (ETH)</th><th>Avg Powder (ETH)</th><th>Checked Tokens</th><th>Status</th></tr>'
            
            time_labels = []
            powder_per_owner_values = []
            
            # Process in chronological order for consistent chart
            ordered_labels = ['-1 Year', '-6 Months', 'Now']
            
            for label in ordered_labels:
                # Find the result for this label
                result_item = next((item for item in results_data if item['label'] == label), None)
                if result_item:
                    block = result_item['block']
                    data = result_item['data']
                    status = "Success" if data['success'] else "<span class='error'>Failed</span>"
                    owners = data['owners']
                    balance = data['balance_eth']
                    checked = data['checked_tokens']
                    avg_powder = (balance / owners) if owners > 0 else Decimal(0)
                    
                    response_html += f'<tr><td>{label}</td><td>{block}</td><td>{owners}</td><td>{balance:.4f}</td><td>{avg_powder:.4f}</td><td>{checked}</td><td>{status}</td></tr>'
                    
                    if data['success']:
                        time_labels.append(label)
                        powder_per_owner_values.append(float(avg_powder))
            
            response_html += '</table>'
            
            # Generate graph
            graph_html = "<p>Not enough data points to generate graph.</p>"
            if len(time_labels) > 1:
                try:
                    fig = go.Figure(data=go.Scatter(x=time_labels, y=powder_per_owner_values, mode='lines+markers'))
                    fig.update_layout(
                        title='Average Owner Powder (ETH) Over Time',
                        xaxis_title='Time Point',
                        yaxis_title='Avg ETH per Owner',
                        yaxis=dict(rangemode='tozero'),
                        margin=dict(l=40, r=20, t=40, b=30),
                        autosize=True,
                        height=400
                    )
                    
                    # Generate HTML version with proper Plotly.js integration
                    import uuid
                    chart_id = f"chart-{uuid.uuid4().hex[:8]}"
                    graph_html = f'''
                    <div id="{chart_id}" style="width: 100%; max-width: 800px; height: 400px; margin: 0 auto;"></div>
                    <script>
                        var plotData = [{json.dumps({
                            'x': time_labels,
                            'y': powder_per_owner_values,
                            'type': 'scatter',
                            'mode': 'lines+markers',
                            'name': 'Avg ETH per Owner'
                        })}];
                        var layout = {{
                            title: 'Average Owner Powder (ETH) Over Time',
                            xaxis: {{ title: 'Time Point' }},
                            yaxis: {{ title: 'Avg ETH per Owner', rangemode: 'tozero' }},
                            margin: {{ l: 40, r: 20, t: 40, b: 30 }}
                        }};
                        Plotly.newPlot('{chart_id}', plotData, layout);
                    </script>
                    '''
                except Exception as e:
                    graph_html = f'<p class="error">Error generating graph: {e}</p>'
            
            response_html += '<h3>Average Owner Powder Trend</h3>'
            response_html += graph_html
            response_html += '</div>'
            
            # Send final result
            yield f"data: {json.dumps({'type': 'complete', 'html': response_html, 'step': total, 'total': total})}\n\n"
            
        except Exception as e:
            yield f"data: {json.dumps({'type': 'error', 'message': str(e)})}\n\n"
    
    return Response(stream_with_context(generate()), mimetype="text/event-stream")

# --- Run Flask App ---
if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)