#!/Library/Frameworks/Python.framework/Versions/3.6/bin/python3
#!/usr/bin/env python3

import requests
import hashlib
import hmac
import time
import sys
import os

MAX_MARKET_DISTANCE_PERCENT=5

def get_bitcoin_average_headers():
    pub_key = os.getenv('BITCOIN_AVERAGE_PUB_KEY') or ''
    sec_key = os.getenv('BITCOIN_AVERAGE_SEC_KEY') or ''
    timestamp = int(time.time())
    payload = '{}.{}'.format(timestamp, pub_key)
    hex_hash = hmac.new(sec_key.encode(), msg=payload.encode(), digestmod=hashlib.sha256).hexdigest()
    signature = '{}.{}'.format(payload, hex_hash)
    return({'X-Signature': signature})

def get_bitcoin_average(from_cur, to_cur, headers):
    url = 'https://apiv2.bitcoinaverage.com/convert/global?from=%s&to=%s&amount=1' % (from_cur.upper(), to_cur.upper())
    return float(requests.get(url=url, headers=headers).json()['price'])

def process_offer(offer, market_price, multiplier, sale=True):
    output = []
    price = float(offer['price'])
    distance_from_market_percent = ((price * multiplier) - market_price) / market_price * 100
    if not sale:
        distance_from_market_percent *= -1
    if distance_from_market_percent > MAX_MARKET_DISTANCE_PERCENT:
        return []
    fiat = False
    if offer['payment_method'] != 'BLOCK_CHAINS':
        output.append('\tPayment method: %s' % offer['payment_method'])
        volume = offer['amount']
        fiat = True
    else:
        volume = offer['volume']
    output.append('\tAmount in BTC: %s - %s' % (offer['min_amount'], volume))
    if fiat:
        output.append('\tPrice for 1: %.2f' % price)
        output.append('\tMaximum: %.2f' % (price * float(volume)))
    else:
        output.append('\tPrice for 1 in USD: %.2f' % (price * multiplier))
        output.append('\tMaximum in USD: %.2f' % (multiplier * float(volume)))
    output.append('\tDistance from market: %.2f%%' % distance_from_market_percent)
    return output

def get_bisq_url(market):
    return('https://market.bisq.io/api/offers?market=%s' % market)
        
def print_offers(title, market, market_price, multiplier=1):
    market = market.lower()
    r = requests.get(get_bisq_url(market))
    new_output = []
    offers = []
    for offer in r.json()[market]['sells']:
        output = process_offer(offer, market_price, multiplier, sale=True)
        if output:
            offers.append(output)
    if offers:
        new_output.append('Sells')
        for offer in offers:
            new_output.append('\n'.join(offer))
            if len(offers) > 1:
                new_output.append('')

    offers = []
    for offer in r.json()[market]['buys']:
        output = process_offer(offer, market_price, multiplier, sale=False)
        if output:
            offers.append(output)
    if offers:
        new_output.append('Buys')
        for offer in offers:
            new_output.append('\n'.join(offer))
            if len(offers) > 1:
                new_output.append('')
    
    if new_output:
        print('\n%s' % title)
        print('\n'.join(new_output))

        
headers = get_bitcoin_average_headers()
current_btc = get_bitcoin_average('btc', 'usd', headers)
current_eur = get_bitcoin_average('btc', 'eur', headers)
current_chf = get_bitcoin_average('btc', 'chf', headers)
current_gbp = get_bitcoin_average('btc', 'gbp', headers)
current_ltc = get_bitcoin_average('ltc', 'usd', headers)
current_eth = get_bitcoin_average('eth', 'usd', headers)

print('Current BTC price in USD: %.2f' % current_btc)
print('Current BTC price in EUR: %.2f' % current_eur)
print('Current BTC price in CHF: %.2f' % current_chf)
print('Current BTC price in GBP: %.2f' % current_gbp)
print('Current LTC price in USD: %.2f' % current_ltc)
print('Current ETH price in USD: %.2f' % current_eth)

print_offers('Bitcoin Offers with USD', 'btc_usd', current_btc)
print_offers('Bitcoin Offers with EUR', 'btc_eur', current_eur)
print_offers('Bitcoin Offers with CHF', 'btc_chf', current_chf)
print_offers('Bitcoin Offers with GBP', 'btc_gbp', current_gbp)
print_offers('Litecoin Offers with BTC', 'ltc_btc', current_ltc, current_btc)
print_offers('Ethereum Offers with BTC', 'eth_btc', current_eth, current_btc)

