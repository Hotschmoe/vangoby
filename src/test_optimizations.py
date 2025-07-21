#!/usr/bin/env python3
"""
Quick performance test of optimization techniques
Tests individual functions without running full Flask app
"""
import time
import asyncio
import aiohttp
from web3 import Web3
import requests

# Test configuration
NODE_URL = 'http://192.168.10.8:8545'
REQUEST_TIMEOUT = 30
TEST_ADDRESSES = [
    '0xd8dA6BF26964aF9D7eEd9e03E53415D37aA96045',  # vitalik.eth
    '0x3C44CdDdB6a900fa2b585dd299e03d12FA4293BC',  # Random address 1
    '0x90F79bf6EB2c4f870365E785982E1f101E93b906',  # Random address 2
]

async def async_batch_get_balances_test(addresses, block='latest'):
    """Test async batch balance fetching"""
    batch = []
    for i, address in enumerate(addresses):
        batch.append({
            'jsonrpc': '2.0',
            'method': 'eth_getBalance',
            'params': [address, block],
            'id': i
        })
    
    timeout = aiohttp.ClientTimeout(total=REQUEST_TIMEOUT)
    async with aiohttp.ClientSession(timeout=timeout) as session:
        async with session.post(NODE_URL, json=batch) as response:
            results = await response.json()
    
    total_balance = 0
    for result in results:
        if 'result' in result and result['result']:
            balance = int(result['result'], 16)
            total_balance += balance
    
    return total_balance

def sync_batch_get_balances_test(addresses, block='latest'):
    """Test sync batch balance fetching"""
    batch = []
    for i, address in enumerate(addresses):
        batch.append({
            'jsonrpc': '2.0',
            'method': 'eth_getBalance',
            'params': [address, block],
            'id': i
        })
    
    response = requests.post(NODE_URL, json=batch, timeout=REQUEST_TIMEOUT)
    results = response.json()
    
    total_balance = 0
    for result in results:
        if 'result' in result and result['result']:
            balance = int(result['result'], 16)
            total_balance += balance
    
    return total_balance

def sync_individual_get_balances_test(addresses, block='latest'):
    """Test individual balance fetching (original slow method)"""
    w3 = Web3(Web3.HTTPProvider(NODE_URL))
    total_balance = 0
    
    for address in addresses:
        try:
            balance = w3.eth.get_balance(address, block_identifier=block)
            total_balance += balance
        except Exception as e:
            print(f"Error getting balance for {address}: {e}")
    
    return total_balance

async def run_performance_comparison():
    """Run performance comparison between different methods"""
    print("=== Performance Comparison ===")
    
    # Test data - multiply addresses to simulate larger datasets
    test_addresses = TEST_ADDRESSES * 10  # 30 addresses
    print(f"Testing with {len(test_addresses)} addresses")
    
    # Test 1: Individual requests (original method)
    print("\n1. Testing individual balance requests (original)...")
    start_time = time.time()
    try:
        total1 = sync_individual_get_balances_test(test_addresses)
        duration1 = time.time() - start_time
        print(f"   Individual requests: {duration1:.2f}s, Total: {total1} wei")
    except Exception as e:
        duration1 = float('inf')
        print(f"   Individual requests failed: {e}")
    
    # Test 2: Sync batch requests
    print("\n2. Testing sync batch requests...")
    start_time = time.time()
    try:
        total2 = sync_batch_get_balances_test(test_addresses)
        duration2 = time.time() - start_time
        print(f"   Sync batch: {duration2:.2f}s, Total: {total2} wei")
    except Exception as e:
        duration2 = float('inf')
        print(f"   Sync batch failed: {e}")
    
    # Test 3: Async batch requests
    print("\n3. Testing async batch requests...")
    start_time = time.time()
    try:
        total3 = await async_batch_get_balances_test(test_addresses)
        duration3 = time.time() - start_time
        print(f"   Async batch: {duration3:.2f}s, Total: {total3} wei")
    except Exception as e:
        duration3 = float('inf')
        print(f"   Async batch failed: {e}")
    
    # Results comparison
    print("\n=== Results Summary ===")
    if duration1 != float('inf'):
        print(f"Individual requests: {duration1:.2f}s")
    if duration2 != float('inf'):
        print(f"Sync batch requests: {duration2:.2f}s")
        if duration1 != float('inf'):
            speedup = duration1 / duration2
            print(f"  -> {speedup:.1f}x faster than individual")
    if duration3 != float('inf'):
        print(f"Async batch requests: {duration3:.2f}s")
        if duration1 != float('inf'):
            speedup = duration1 / duration3
            print(f"  -> {speedup:.1f}x faster than individual")
        if duration2 != float('inf'):
            speedup = duration2 / duration3
            print(f"  -> {speedup:.1f}x faster than sync batch")

if __name__ == '__main__':
    try:
        # Try to use existing event loop
        loop = asyncio.get_event_loop()
    except RuntimeError:
        # Create new event loop if none exists
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
    
    loop.run_until_complete(run_performance_comparison())