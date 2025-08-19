from flask import Flask, request, jsonify
import asyncio
from Crypto.Cipher import AES
from Crypto.Util.Padding import pad
from google.protobuf.json_format import MessageToJson
import binascii
import aiohttp
import requests
import json
import like_pb2
import like_count_pb2
import uid_generator_pb2
from google.protobuf.message import DecodeError
from datetime import datetime, timedelta
from pymongo import MongoClient
from bson.objectid import ObjectId
import secrets
import string
from apscheduler.schedulers.background import BackgroundScheduler
import atexit

app = Flask(__name__)

# MongoDB configuration
client = MongoClient(your mongo db url)
db = client.yourdb
keys_collection = db.api_keys

# Initialize scheduler for daily reset
scheduler = BackgroundScheduler(daemon=True)
scheduler.start()
atexit.register(lambda: scheduler.shutdown())

def reset_remaining_requests():
    """Reset remaining requests for all active keys to their total_requests"""
    try:
        now = datetime.now()
        active_keys = keys_collection.find({
            "is_active": True,
            "expires_at": {"$gt": now}
        })
        
        for key in active_keys:
            keys_collection.update_one(
                {"_id": key["_id"]},
                {
                    "$set": {
                        "remaining_requests": key["total_requests"],
                        "last_reset": now
                    }
                }
            )
        app.logger.info(f"Successfully reset requests at {now}")
    except Exception as e:
        app.logger.error(f"Error in reset_remaining_requests: {e}")

# Schedule daily reset at midnight
scheduler.add_job(
    reset_remaining_requests,
    'cron',
    hour=0,
    minute=0,
    second=0,
    timezone='UTC'
)

def load_tokens(server_name):
    try:
        if server_name == "IND":
            with open("token_ind.json", "r") as f:
                tokens = json.load(f)
        elif server_name in {"BR", "US", "SAC", "NA"}:
            with open("token_br.json", "r") as f:
                tokens = json.load(f)
        else:
            with open("token_bd.json", "r") as f:
                tokens = json.load(f)
        return tokens
    except Exception as e:
        app.logger.error(f"Error loading tokens for server {server_name}: {e}")
        return None

def encrypt_message(plaintext):
    try:
        key = b'Yg&tc%DEuh6%Zc^8'
        iv = b'6oyZDr22E3ychjM%'
        cipher = AES.new(key, AES.MODE_CBC, iv)
        padded_message = pad(plaintext, AES.block_size)
        encrypted_message = cipher.encrypt(padded_message)
        return binascii.hexlify(encrypted_message).decode('utf-8')
    except Exception as e:
        app.logger.error(f"Error encrypting message: {e}")
        return None

def create_protobuf_message(user_id, region):
    try:
        message = like_pb2.like()
        message.uid = int(user_id)
        message.region = region
        return message.SerializeToString()
    except Exception as e:
        app.logger.error(f"Error creating protobuf message: {e}")
        return None

async def send_request(encrypted_uid, token, url):
    try:
        edata = bytes.fromhex(encrypted_uid)
        headers = {
            'User-Agent': "Dalvik/2.1.0 (Linux; U; Android 9; ASUS_Z01QD Build/PI)",
            'Connection': "Keep-Alive",
            'Accept-Encoding': "gzip",
            'Authorization': f"Bearer {token}",
            'Content-Type': "application/x-www-form-urlencoded",
            'Expect': "100-continue",
            'X-Unity-Version': "2018.4.11f1",
            'X-GA': "v1 1",
            'ReleaseVersion': "OB49"
        }
        async with aiohttp.ClientSession() as session:
            async with session.post(url, data=edata, headers=headers) as response:
                if response.status != 200:
                    app.logger.error(f"Request failed with status code: {response.status}")
                    return response.status
                return await response.text()
    except Exception as e:
        app.logger.error(f"Exception in send_request: {e}")
        return None

async def send_multiple_requests(uid, server_name, url):
    try:
        region = server_name
        protobuf_message = create_protobuf_message(uid, region)
        if protobuf_message is None:
            app.logger.error("Failed to create protobuf message.")
            return None
        encrypted_uid = encrypt_message(protobuf_message)
        if encrypted_uid is None:
            app.logger.error("Encryption failed.")
            return None
        tasks = []
        tokens = load_tokens(server_name)
        if tokens is None:
            app.logger.error("Failed to load tokens.")
            return None
        for i in range(100):
            token = tokens[i % len(tokens)]["token"]
            tasks.append(send_request(encrypted_uid, token, url))
        results = await asyncio.gather(*tasks, return_exceptions=True)
        return results
    except Exception as e:
        app.logger.error(f"Exception in send_multiple_requests: {e}")
        return None

def create_protobuf(uid):
    try:
        message = uid_generator_pb2.uid_generator()
        message.saturn_ = int(uid)
        message.garena = 1
        return message.SerializeToString()
    except Exception as e:
        app.logger.error(f"Error creating uid protobuf: {e}")
        return None

def enc(uid):
    protobuf_data = create_protobuf(uid)
    if protobuf_data is None:
        return None
    encrypted_uid = encrypt_message(protobuf_data)
    return encrypted_uid

def make_request(encrypt, server_name, token):
    try:
        if server_name == "IND":
            url = "https://client.ind.freefiremobile.com/GetPlayerPersonalShow"
        elif server_name in {"BR", "US", "SAC", "NA"}:
            url = "https://client.us.freefiremobile.com/GetPlayerPersonalShow"
        else:
            url = "https://clientbp.ggblueshark.com/GetPlayerPersonalShow"
        edata = bytes.fromhex(encrypt)
        headers = {
            'User-Agent': "Dalvik/2.1.0 (Linux; U; Android 9; ASUS_Z01QD Build/PI)",
            'Connection': "Keep-Alive",
            'Accept-Encoding': "gzip",
            'Authorization': f"Bearer {token}",
            'Content-Type': "application/x-www-form-urlencoded",
            'Expect': "100-continue",
            'X-Unity-Version': "2018.4.11f1",
            'X-GA': "v1 1",
            'ReleaseVersion': "OB49"
        }
        response = requests.post(url, data=edata, headers=headers, verify=False)
        hex_data = response.content.hex()
        binary = bytes.fromhex(hex_data)
        decode = decode_protobuf(binary)
        if decode is None:
            app.logger.error("Protobuf decoding returned None.")
        return decode
    except Exception as e:
        app.logger.error(f"Error in make_request: {e}")
        return None

def decode_protobuf(binary):
    try:
        items = like_count_pb2.Info()
        items.ParseFromString(binary)
        return items
    except DecodeError as e:
        app.logger.error(f"Error decoding Protobuf data: {e}")
        return None
    except Exception as e:
        app.logger.error(f"Unexpected error during protobuf decoding: {e}")
        return None

def authenticate_key(api_key):
    """Check if API key exists and is valid"""
    try:
        key_data = keys_collection.find_one({"key": api_key})
        if not key_data:
            return None
        
        # Check expiration
        now = datetime.now()
        if 'expires_at' in key_data and now > key_data['expires_at']:
            # Mark as inactive if expired
            keys_collection.update_one(
                {"key": api_key},
                {"$set": {"is_active": False}}
            )
            return None
        
        # Check if key is active
        if 'is_active' in key_data and not key_data['is_active']:
            return None
        
        # Check if we need to reset remaining requests (new day)
        if 'last_reset' in key_data:
            last_reset = key_data['last_reset']
            if isinstance(last_reset, str):
                last_reset = datetime.fromisoformat(last_reset)
            if last_reset.date() < now.date():
                keys_collection.update_one(
                    {"key": api_key},
                    {"$set": {
                        "remaining_requests": key_data['total_requests'],
                        "last_reset": now
                    }}
                )
                key_data['remaining_requests'] = key_data['total_requests']
        
        return key_data
    except Exception as e:
        app.logger.error(f"Error in authenticate_key: {e}")
        return None

def update_key_usage(api_key, decrement=1):
    """Decrement remaining requests count for a key only when likes are given"""
    try:
        keys_collection.update_one(
            {"key": api_key},
            {
                "$inc": {"remaining_requests": -decrement},
                "$set": {"last_used": datetime.now()}
            }
        )
    except Exception as e:
        app.logger.error(f"Error updating key usage: {e}")

@app.route('/api/key/create', methods=['POST'])
def create_key():
    try:
        data = request.get_json()
        custom_key = data.get('custom_key')
        total_requests = int(data.get('total_requests', 1000))
        expiry_days = int(data.get('expiry_days', 30))
        notes = data.get('notes', '')
        
        if custom_key:
            if keys_collection.find_one({"key": custom_key}):
                return jsonify({"error": "Custom key already exists"}), 400
            api_key = custom_key
        else:
            alphabet = string.ascii_letters + string.digits
            api_key = ''.join(secrets.choice(alphabet) for _ in range(32))
        
        expires_at = datetime.now() + timedelta(days=expiry_days)
        
        key_doc = {
            "key": api_key,
            "created_at": datetime.now(),
            "expires_at": expires_at,
            "total_requests": total_requests,
            "remaining_requests": total_requests,
            "notes": notes,
            "is_active": True,
            "last_reset": datetime.now()
        }
        
        keys_collection.insert_one(key_doc)
        
        return jsonify({
            "message": "API key created successfully",
            "key": api_key,
            "expires_at": expires_at.isoformat(),
            "total_requests": total_requests,
            "notes": notes
        }), 201
    except Exception as e:
        app.logger.error(f"Error creating API key: {e}")
        return jsonify({"error": str(e)}), 500

@app.route('/api/key/check', methods=['GET'])
def check_key():
    """Check the status and details of an API key"""
    try:
        api_key = request.headers.get('X-API-KEY') or request.args.get('key')
        if not api_key:
            return jsonify({"error": "API key is required"}), 401
        
        key_data = authenticate_key(api_key)
        if not key_data:
            return jsonify({"error": "Invalid or expired API key"}), 403
        
        # Remove MongoDB-specific fields before returning
        key_data.pop('_id', None)
        
        # Convert datetime objects to strings
        if 'created_at' in key_data and isinstance(key_data['created_at'], datetime):
            key_data['created_at'] = key_data['created_at'].isoformat()
        if 'expires_at' in key_data and isinstance(key_data['expires_at'], datetime):
            key_data['expires_at'] = key_data['expires_at'].isoformat()
        if 'last_reset' in key_data and isinstance(key_data['last_reset'], datetime):
            key_data['last_reset'] = key_data['last_reset'].isoformat()
        if 'last_used' in key_data and isinstance(key_data['last_used'], datetime):
            key_data['last_used'] = key_data['last_used'].isoformat()
        
        return jsonify(key_data), 200
    except Exception as e:
        app.logger.error(f"Error checking API key: {e}")
        return jsonify({"error": str(e)}), 500

@app.route('/api/key/remove', methods=['DELETE'])
def remove_key():
    """Remove an API key (mark as inactive)"""
    try:
        api_key = request.headers.get('X-API-KEY') or request.args.get('key')
        if not api_key:
            return jsonify({"error": "API key is required"}), 401
        
        # First authenticate the key
        key_data = authenticate_key(api_key)
        if not key_data:
            return jsonify({"error": "Invalid or expired API key"}), 403
        
        # Mark the key as inactive instead of deleting it
        result = keys_collection.update_one(
            {"key": api_key},
            {"$set": {"is_active": False}}
        )
        
        if result.modified_count == 1:
            return jsonify({"message": "API key deactivated successfully"}), 200
        else:
            return jsonify({"error": "Failed to deactivate API key"}), 400
    except Exception as e:
        app.logger.error(f"Error removing API key: {e}")
        return jsonify({"error": str(e)}), 500

@app.route('/api/key/update', methods=['PUT'])
def update_key():
    """Update an API key's properties"""
    try:
        api_key = request.headers.get('X-API-KEY') or request.args.get('key')
        if not api_key:
            return jsonify({"error": "API key is required"}), 401
        
        # First authenticate the key
        key_data = authenticate_key(api_key)
        if not key_data:
            return jsonify({"error": "Invalid or expired API key"}), 403
        
        data = request.get_json()
        update_fields = {}
        
        if 'total_requests' in data:
            try:
                total_requests = int(data['total_requests'])
                update_fields['total_requests'] = total_requests
                # Also update remaining_requests if increasing total_requests
                if total_requests > key_data.get('total_requests', 0):
                    update_fields['remaining_requests'] = total_requests - (key_data.get('total_requests', 0) - key_data.get('remaining_requests', 0))
            except ValueError:
                return jsonify({"error": "total_requests must be an integer"}), 400
        
        if 'expiry_days' in data:
            try:
                expiry_days = int(data['expiry_days'])
                new_expiry = datetime.now() + timedelta(days=expiry_days)
                update_fields['expires_at'] = new_expiry
            except ValueError:
                return jsonify({"error": "expiry_days must be an integer"}), 400
        
        if 'is_active' in data:
            update_fields['is_active'] = bool(data['is_active'])
        
        if 'notes' in data:
            update_fields['notes'] = str(data['notes'])
        
        if not update_fields:
            return jsonify({"error": "No valid fields to update"}), 400
        
        result = keys_collection.update_one(
            {"key": api_key},
            {"$set": update_fields}
        )
        
        if result.modified_count == 1:
            return jsonify({"message": "API key updated successfully"}), 200
        else:
            return jsonify({"error": "No changes made to API key"}), 400
    except Exception as e:
        app.logger.error(f"Error updating API key: {e}")
        return jsonify({"error": str(e)}), 500

@app.route('/like', methods=['GET'])
def handle_requests():
    api_key = request.headers.get('X-API-KEY') or request.args.get('key')
    if not api_key:
        return jsonify({"error": "API key is required"}), 401
    
    key_data = authenticate_key(api_key)
    if not key_data:
        return jsonify({"error": "Invalid or expired API key"}), 403
    
    # Check remaining requests
    if key_data.get('remaining_requests', 0) <= 0:
        return jsonify({
            "error": "No remaining requests",
            "status": 0,
            "next_reset": (datetime.now() + timedelta(days=1)).replace(hour=0, minute=0, second=0).isoformat()
        }), 429
    
    uid = request.args.get("uid")
    server_name = request.args.get("server_name", "").upper()
    if not uid or not server_name:
        return jsonify({"error": "UID and server_name are required"}), 400

    try:
        def process_request():
            tokens = load_tokens(server_name)
            if tokens is None:
                raise Exception("Failed to load tokens.")
            token = tokens[0]['token']
            encrypted_uid = enc(uid)
            if encrypted_uid is None:
                raise Exception("Encryption of UID failed.")

            # First request to get initial data
            before = make_request(encrypted_uid, server_name, token)
            if before is None:
                raise Exception("Failed to retrieve initial player info.")
            
            try:
                jsone = MessageToJson(before)
                data_before = json.loads(jsone)
                account_info = data_before.get('AccountInfo', {})
                before_like = int(account_info.get('Likes', 0))
                player_level = int(account_info.get('Level', 0))
            except Exception as e:
                raise Exception(f"Error processing before data: {str(e)}")

            # Determine the correct URL for likes
            if server_name == "IND":
                url = "https://client.ind.freefiremobile.com/LikeProfile"
            elif server_name in {"BR", "US", "SAC", "NA"}:
                url = "https://client.us.freefiremobile.com/LikeProfile"
            else:
                url = "https://clientbp.ggblueshark.com/LikeProfile"

            # Send like requests
            asyncio.run(send_multiple_requests(uid, server_name, url))

            # Second request to get updated data
            after = make_request(encrypted_uid, server_name, token)
            if after is None:
                raise Exception("Failed to retrieve player info after like requests.")
            
            try:
                jsone_after = MessageToJson(after)
                data_after = json.loads(jsone_after)
                account_info_after = data_after.get('AccountInfo', {})
                after_like = int(account_info_after.get('Likes', 0))
                player_uid = int(account_info_after.get('UID', 0))
                player_name = str(account_info_after.get('PlayerNickname', ''))
                like_given = after_like - before_like
                player_level = int(account_info_after.get('Level', 0))
            except Exception as e:
                raise Exception(f"Error processing after data: {str(e)}")
            
            # Determine status and update key usage
            if like_given > 0:
                status = 1
                update_key_usage(api_key, 1)  # Always decrement by 1 when likes are given
            else:
                status = 2
            
            # Get updated key info
            updated_key_data = authenticate_key(api_key)
            if not updated_key_data:
                raise Exception("Failed to retrieve updated key info")
            
            response = {
                "response": {
                    "KeyExpiresAt": updated_key_data['expires_at'].isoformat(),
                    "KeyRemainingRequests": f"{updated_key_data['remaining_requests']}/{updated_key_data['total_requests']}",
                    "LikesGivenByAPI": like_given,
                    "LikesafterCommand": after_like,
                    "LikesbeforeCommand": before_like,
                    "PlayerNickname": player_name,
                    "UID": player_uid
                },
                "status": status
            }
            
            return response

        result = process_request()
        return jsonify(result)
    except Exception as e:
        app.logger.error(f"Error processing request: {e}")
        return jsonify({"error": str(e), "status": 0}), 500

if __name__ == '__main__':
    app.run(debug=True)
