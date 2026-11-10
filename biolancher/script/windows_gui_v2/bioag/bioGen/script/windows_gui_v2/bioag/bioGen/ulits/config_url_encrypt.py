import base64
import sys

def xor_encrypt(plain_text: str, key: str) -> str:
    if not key:
        raise ValueError("encrypt_key cannot be empty")
    
    key_bytes = key.encode("utf-8")
    plain_bytes = plain_text.encode("utf-8")
    
    encrypted = bytes(b ^ key_bytes[i % len(key_bytes)] for i, b in enumerate(plain_bytes))
    return base64.b64encode(encrypted).decode("utf-8")


if __name__ == "__main__":
    if len(sys.argv) != 3:
        print("Usage: python xor_encrypt.py <text> <key>")
        sys.exit(1)
    
    text = sys.argv[1]
    key = sys.argv[2]
    
    try:
        result = xor_encrypt(text, key)
        print(result)
    except Exception as e:
        print(f"Error: {e}")
        sys.exit(1)