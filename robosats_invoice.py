"""Validate Lightning invoice amounts and calculate buyer payouts."""
import re


# The BOLT11 amount units expressed in millisats.
MSAT = {'': 100_000_000_000, 'm': 100_000_000, 'u': 100_000, 'n': 100}


def invoice_msats(invoice):
    hrp, separator, data = invoice.lower().rpartition('1')
    match = re.fullmatch(r'lnbc([0-9]+)([munp]?)', hrp)
    if not match or not separator or not re.fullmatch(r'[qpzry9x8gf2tvdw0s3jn54khce6mua7l]{111,}', data):
        raise ValueError('Expected a mainnet BOLT11 invoice with an explicit amount.')
    amount, unit = match.groups()
    value = int(amount)
    if unit == 'p':
        if value % 10:
            raise ValueError('Invalid BOLT11 amount.')
        return value // 10
    return value * MSAT[unit]


def payout_amount(balance, ppm):
    return balance if ppm is None else int(balance - balance * (ppm / 1_000_000))

