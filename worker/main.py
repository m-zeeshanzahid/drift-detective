import os
import time
import requests
import logging
from datetime import datetime, timezone
from dotenv import load_dotenv

load_dotenv()
logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
logger = logging.getLogger(__name__)

SUPERPLANE_API_URL    = os.getenv('SUPERPLANE_API_URL', 'https://api.superplane.com')
SUPERPLANE_API_KEY    = os.getenv('SUPERPLANE_API_KEY')
SUPERPLANE_ORG        = os.getenv('SUPERPLANE_ORG')
SUPERPLANE_APP        = os.getenv('SUPERPLANE_APP_NAME', 'drift-detective')
POLL_INTERVAL_SECONDS = int(os.getenv('POLL_INTERVAL_SECONDS', '300'))

HEADERS = {
    'Authorization': f'Bearer {SUPERPLANE_API_KEY}',
    'Content-Type': 'application/json'
}


def trigger_drift_scan():
    url     = f'{SUPERPLANE_API_URL}/v1/organizations/{SUPERPLANE_ORG}/apps/{SUPERPLANE_APP}/triggers'
    payload = {
        'type': 'manual',
        'inputs': {
            'triggered_by': 'render-worker',
            'timestamp': datetime.now(timezone.utc).isoformat()
        }
    }
    try:
        response = requests.post(url, json=payload, headers=HEADERS, timeout=30)
        response.raise_for_status()
        run_id = response.json().get('id', 'unknown')
        logger.info(f'Triggered drift scan. Run ID: {run_id}')
        return run_id
    except requests.RequestException as e:
        logger.error(f'Failed to trigger drift scan: {e}')
        return None


def main():
    logger.info(f'Drift Detective Worker starting. Poll: {POLL_INTERVAL_SECONDS}s')
    trigger_drift_scan()  # run immediately on startup
    while True:
        time.sleep(POLL_INTERVAL_SECONDS)
        logger.info('Running scheduled drift scan...')
        trigger_drift_scan()


if __name__ == '__main__':
    main()
