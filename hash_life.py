import hashlib
import os
import base64

salt = input("Enter a SALT: ").encode()
salt_ret = input("Re Enter a SALT: ").encode()

assert salt == salt_ret

password = input("Enter password: ")
password_ret = input("Re Enter password: ")

assert password == password_ret


key = hashlib.pbkdf2_hmac(
    'sha256', # The hash digest algorithm for HMAC
    password.encode('utf-8'), # Convert the password to bytes
    salt, # Provide the salt
    100000, # It is recommended to use at least 100,000 iterations of SHA-256 
    dklen=512 # Get a 512 byte key
)

base64_bytes = base64.b64encode(key)
base64_message = base64_bytes.decode('ascii')

print("------------>"+base64_message+"<------------")
