# Flask server with Ethereum RPC proxy endpoints

from flask import Flask, request, jsonify
from flask_cors import CORS
import requests
import json

# Import configuration from ens_balance.py
from ens_balance import NODE_URL, REQUEST_TIMEOUT

# Create Flask app instance
app = Flask(__name__)

# Enable CORS for your Flask app
CORS(app)

# Add this new route to your existing Flask server
@app.route('/eth-proxy', methods=['POST'])
def eth_proxy():
    """Proxy endpoint for Ethereum RPC calls to bypass CORS"""
    try:
        # Get the JSON-RPC request from the frontend
        rpc_request = request.get_json()
        
        # Forward the request to your Erigon node
        response = requests.post(
            NODE_URL,
            json=rpc_request,
            timeout=REQUEST_TIMEOUT,
            headers={'Content-Type': 'application/json'}
        )
        
        # Return the response back to the frontend
        return jsonify(response.json())
        
    except Exception as e:
        return jsonify({
            'error': {
                'code': -1,
                'message': str(e)
            }
        }), 500

@app.route('/eth-batch-proxy', methods=['POST'])
def eth_batch_proxy():
    """Proxy endpoint for batch Ethereum RPC calls"""
    try:
        # Get the batch request from the frontend
        batch_request = request.get_json()
        
        # Forward the batch request to your Erigon node
        response = requests.post(
            NODE_URL,
            json=batch_request,
            timeout=REQUEST_TIMEOUT,
            headers={'Content-Type': 'application/json'}
        )
        
        # Return the batch response back to the frontend
        return jsonify(response.json())
        
    except Exception as e:
        return jsonify({
            'error': {
                'code': -1,
                'message': str(e)
            }
        }), 500

@app.route('/health', methods=['GET'])
def health_check():
    """Health check endpoint"""
    return jsonify({'status': 'ok', 'node_url': NODE_URL})

if __name__ == '__main__':
    print(f"Starting Flask server with Ethereum node at: {NODE_URL}")
    app.run(host='0.0.0.0', port=5000, debug=True)

# If you don't have flask-cors installed, install it:
# pip install flask-cors