from flask import Flask, request, jsonify
from flask_cors import CORS
import subprocess
import logging
import os

logging.basicConfig(level=logging.INFO)
app = Flask(__name__)
CORS(app)

@app.route('/')
def index():
    return open('Dash_final.html', encoding='utf-8').read()

@app.route('/run', methods=['POST'])
def run():
    data = request.get_json(silent=True) or {}

    title = str(data.get('title', '')).strip()
    if not title:
        return jsonify({'error': 'Invalid payload'}), 400

    logging.info("Running autologin.py for defect: %s", title[:80])

    try:
        result = subprocess.run(
            ['python', 'autologin.py'],
            capture_output=True,
            text=True,
            timeout=60
        )

        logging.info("autologin.py exited with code %d", result.returncode)

        return jsonify({
            'status': 'ok',
            'exit_code': result.returncode,
            'output': result.stdout,
            'stderr': result.stderr,
            'pid': os.getpid()
        })

    except subprocess.TimeoutExpired:
        return jsonify({
            'status': 'error',
            'exit_code': -1,
            'output': '',
            'stderr': 'autologin.py timed out after 60 seconds',
            'pid': os.getpid()
        }), 500

    except FileNotFoundError:
        return jsonify({
            'status': 'error',
            'exit_code': -1,
            'output': '',
            'stderr': 'autologin.py not found in the same folder as app.py',
            'pid': os.getpid()
        }), 500

    except Exception as ex:
        return jsonify({
            'status': 'error',
            'exit_code': -1,
            'output': '',
            'stderr': str(ex),
            'pid': os.getpid()
        }), 500

if __name__ == '__main__':
    app.run(debug=False, host='127.0.0.1', port=5000)
