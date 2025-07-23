import requests
import time
import logging
import datetime

# --- Configuration ---
# Use a known, relatively stable NFT collection for consistent testing
TEST_COLLECTION_ADDRESS = '0x79FCDEF22feeD20eDDacbB2587640e45491b757f' # MFer example
APP_URL = 'http://127.0.0.1:5000/get-owners-powder' # Assuming app runs locally
APP_URL_OPTIMIZED = 'http://127.0.0.1:5001/get-owners-powder' # Optimized version
LOG_FILE = 'performance.log'
NUM_RUNS = 3 # Number of times to run the test for an average

# --- Logging Setup ---
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[
        logging.FileHandler(LOG_FILE),
        logging.StreamHandler() # Also print logs to console
    ]
)

def run_performance_test(collection_address):
    """Sends a request to the app, times it, and logs the result."""
    logging.info(f"Starting test run for collection: {collection_address}")
    payload = {'collection_address': collection_address}
    start_time = time.time()
    
    try:
        response = requests.post(APP_URL, data=payload, timeout=300) # Increased timeout for potentially long requests
        end_time = time.time()
        duration = end_time - start_time
        
        response.raise_for_status() # Raise an exception for bad status codes (4xx or 5xx)
        
        # Basic check for expected content (can be made more robust)
        if "Summary Over Time" in response.text and "Average Owner Powder Trend" in response.text:
             logging.info(f"Test run SUCCESSFUL for {collection_address}. Duration: {duration:.2f} seconds.")
             return duration
        else:
            logging.error(f"Test run FAILED for {collection_address}. Unexpected response content.")
            logging.debug(f"Response Text (first 500 chars):\n{response.text[:500]}")
            return None
            
    except requests.exceptions.Timeout:
        end_time = time.time()
        duration = end_time - start_time
        logging.error(f"Test run FAILED for {collection_address}. Request timed out after {duration:.2f} seconds.")
        return None
    except requests.exceptions.RequestException as e:
        end_time = time.time()
        duration = end_time - start_time
        logging.error(f"Test run FAILED for {collection_address}. Request error: {e}")
        return None
    except Exception as e:
        end_time = time.time()
        duration = end_time - start_time
        logging.error(f"Test run FAILED for {collection_address}. An unexpected error occurred: {e}")
        return None

def compare_apps():
    """Compare performance between original and optimized apps"""
    
    # Test original app (port 5000)
    logging.info("=== Testing ORIGINAL App ===")
    logging.info(f"Target App URL: {APP_URL}")
    
    original_durations = []
    for i in range(NUM_RUNS):
        logging.info(f"--- Original Run {i+1}/{NUM_RUNS} ---")
        duration = run_performance_test(TEST_COLLECTION_ADDRESS)
        if duration is not None:
            original_durations.append(duration)
        time.sleep(2)
    
    # Test optimized app (port 5001)
    logging.info("=== Testing OPTIMIZED App ===")
    logging.info(f"Target App URL: {APP_URL_OPTIMIZED}")
    
    optimized_durations = []
    for i in range(NUM_RUNS):
        logging.info(f"--- Optimized Run {i+1}/{NUM_RUNS} ---")
        payload = {'collection_address': TEST_COLLECTION_ADDRESS}
        start_time = time.time()
        
        try:
            response = requests.post(APP_URL_OPTIMIZED, data=payload, timeout=300)
            duration = time.time() - start_time
            
            if response.status_code == 200 and "Summary Over Time" in response.text:
                logging.info(f"Optimized run SUCCESSFUL. Duration: {duration:.2f} seconds.")
                optimized_durations.append(duration)
            else:
                logging.error(f"Optimized run FAILED. Status: {response.status_code}")
        except Exception as e:
            duration = time.time() - start_time
            logging.error(f"Optimized run FAILED after {duration:.2f}s: {e}")
        
        time.sleep(2)
    
    # Calculate and compare results
    if original_durations:
        avg_original = sum(original_durations) / len(original_durations)
        min_original = min(original_durations)
        max_original = max(original_durations)
        
        logging.info("=== ORIGINAL Performance Summary ===")
        logging.info(f"Successful runs: {len(original_durations)}/{NUM_RUNS}")
        logging.info(f"Average Duration: {avg_original:.2f} seconds")
        logging.info(f"Min Duration: {min_original:.2f} seconds")
        logging.info(f"Max Duration: {max_original:.2f} seconds")
    else:
        avg_original = None
        logging.warning("No successful original runs completed.")
    
    if optimized_durations:
        avg_optimized = sum(optimized_durations) / len(optimized_durations)
        min_optimized = min(optimized_durations)
        max_optimized = max(optimized_durations)
        
        logging.info("=== OPTIMIZED Performance Summary ===")
        logging.info(f"Successful runs: {len(optimized_durations)}/{NUM_RUNS}")
        logging.info(f"Average Duration: {avg_optimized:.2f} seconds")
        logging.info(f"Min Duration: {min_optimized:.2f} seconds")
        logging.info(f"Max Duration: {max_optimized:.2f} seconds")
        
        # Calculate speedup
        if avg_original and avg_optimized:
            speedup = avg_original / avg_optimized
            logging.info("=== PERFORMANCE COMPARISON ===")
            logging.info(f"Original app average: {avg_original:.2f}s")
            logging.info(f"Optimized app average: {avg_optimized:.2f}s")
            logging.info(f"Speedup: {speedup:.1f}x faster")
            
        return avg_optimized, optimized_durations
    else:
        logging.warning("No successful optimized runs completed.")
        return None, []

if __name__ == '__main__':
    logging.info("=== Starting Performance Measurement ===")
    logging.info(f"Test Collection: {TEST_COLLECTION_ADDRESS}")
    logging.info(f"Number of runs: {NUM_RUNS}")
    
    # Test just the optimized version for now
    avg_optimized, opt_durations = compare_apps()
    
    logging.info("=== Performance Measurement Finished ===")
