import requests
import time
import logging
import datetime

# --- Configuration ---
# Use a known, relatively stable NFT collection for consistent testing
TEST_COLLECTION_ADDRESS = '0x79FCDEF22feeD20eDDacbB2587640e45491b757f' # MFer example
APP_URL = 'http://127.0.0.1:5000/get-owners-powder' # Assuming app runs locally
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

if __name__ == '__main__':
    logging.info("=== Starting Performance Measurement ===")
    logging.info(f"Target App URL: {APP_URL}")
    logging.info(f"Test Collection: {TEST_COLLECTION_ADDRESS}")
    logging.info(f"Number of runs: {NUM_RUNS}")
    
    durations = []
    for i in range(NUM_RUNS):
        logging.info(f"--- Run {i+1}/{NUM_RUNS} ---")
        duration = run_performance_test(TEST_COLLECTION_ADDRESS)
        if duration is not None:
            durations.append(duration)
        time.sleep(2) # Small delay between runs
        
    if durations:
        average_duration = sum(durations) / len(durations)
        min_duration = min(durations)
        max_duration = max(durations)
        logging.info("=== Performance Measurement Summary ===")
        logging.info(f"Successful runs: {len(durations)}/{NUM_RUNS}")
        logging.info(f"Average Duration: {average_duration:.2f} seconds")
        logging.info(f"Min Duration: {min_duration:.2f} seconds")
        logging.info(f"Max Duration: {max_duration:.2f} seconds")
    else:
        logging.warning("=== Performance Measurement Summary ===")
        logging.warning("No successful runs completed.")
    
    logging.info("=== Performance Measurement Finished ===")
