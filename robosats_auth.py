"""Derive an order credential using the RoboSats Garage Key format."""
import hashlib
import hmac

BECH32 = 'qpzry9x8gf2tvdw0s3jn54khce6mua7l'
GENERATORS = (0x3b6a57b2, 0x26508e6d, 0x1ea119fa, 0x3d4233dd, 0x2a1462b3)
BASE62 = 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789'
CURVE_ORDER = 0xFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFEBAAEDCE6AF48A03BBFD25E8CD0364141


def decode_garage_key(value):
    if not value.lower().startswith('robo1'):
        raise ValueError('The Garage Key must start with robo1.')
    if len(value) != 63:
        raise ValueError(f'The pasted Garage Key has {len(value)} characters. Copy all 63 characters from RoboSats.')
    if value not in (value.lower(), value.upper()):
        raise ValueError('The pasted Garage Key mixes upper and lower case. Copy it directly from RoboSats.')
    words = [BECH32.find(char) for char in value.lower()[5:]]
    if -1 in words:
        raise ValueError('Invalid RoboSats Garage Key characters.')
    prefix = 'robo'
    checksum = 1
    for word in [ord(c) >> 5 for c in prefix] + [0] + [ord(c) & 31 for c in prefix] + words:
        top = checksum >> 25
        checksum = ((checksum & 0x1FFFFFF) << 5) ^ word
        for bit, generator in enumerate(GENERATORS):
            if (top >> bit) & 1:
                checksum ^= generator
    if checksum != 1 or words[-7] & 15:
        raise ValueError('Invalid Garage Key checksum or padding. Check your copy.')
    payload = 0
    for word in words[:-6]:
        payload = (payload << 5) | word
    return (payload >> 4).to_bytes(32, 'big')


def garage_robot_token(seed, index):
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import ec

    if not 0 <= index < 2**31:
        raise ValueError('Robot index must be between 0 and 2147483647.')
    material = hmac.digest(b'Bitcoin seed', hashlib.sha512(seed).digest(), 'sha512')
    key = int.from_bytes(material[:32], 'big')
    for child in (2**31 + 44, 2**31 + 88, 2**31 + index, 0):
        if child >= 2**31:
            parent = b'\0' + key.to_bytes(32, 'big')
        else:
            parent = ec.derive_private_key(key, ec.SECP256K1()).public_key().public_bytes(
                serialization.Encoding.X962, serialization.PublicFormat.CompressedPoint)
        material = hmac.digest(material[32:], parent + child.to_bytes(4, 'big'), 'sha512')
        offset = int.from_bytes(material[:32], 'big')
        key = (key + offset) % CURVE_ORDER
        if offset >= CURVE_ORDER or not key:
            raise ValueError('Could not derive the RoboSats robot identity.')
    chars = []
    for _ in range(36):
        key, digit = divmod(key, 62)
        chars.append(BASE62[digit])
    return ''.join(reversed(chars))


def robot_authorization(token):
    import base91

    return 'Token ' + base91.encode(hashlib.sha256(token.encode('ascii')).digest())


def garage_authorization(seed, index):
    return robot_authorization(garage_robot_token(seed, index))
