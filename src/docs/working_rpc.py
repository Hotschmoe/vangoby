import requests
import json
from web3 import Web3

# Connect to your Erigon node
NODE_URL = 'http://192.168.10.8:8545'
REQUEST_TIMEOUT = 30  # seconds

try:
    provider = Web3.HTTPProvider(NODE_URL, request_kwargs={'timeout': REQUEST_TIMEOUT})
    w3 = Web3(provider)

    # Try a direct RPC call instead of is_connected()
    block_number = w3.eth.block_number
    print(f"Successfully connected to {NODE_URL}. Current block: {block_number}")

except Exception as e:
    print(f"Failed to connect or call method on the Ethereum node at {NODE_URL}. Error: {e}")
    exit(1)

# Step 1: Resolve ENS name to address
ens_name = 'cory.eth'
try:
    address = w3.ens.address(ens_name)
    if address is None:
        print(f"Could not resolve ENS name: {ens_name}")
        exit(1)
except Exception as e:
    print(f"Error resolving ENS name: {e}")
    exit(1)

# Step 2: Get balance
try:
    balance_wei = w3.eth.get_balance(address)
    balance_eth = w3.from_wei(balance_wei, 'ether')
    
    print(f"Address: {address}")
    print(f"Balance: {balance_eth} ETH")
except Exception as e:
    print(f"Error getting balance: {e}")