#!/usr/bin/env python3
#
# This creates 100 files in the current directory of the format bisq_N.txt where N is the maximum market distance percent.
# You must set environment variables BITCOIN_AVERAGE_PUB_KEY and BITCOIN_AVERAGE_SEC_KEY based on an API key for bitcoinaverage.com.

import requests
import hashlib
import hmac
import time
import sys
import os

MARKETS=('btc_usd', 'btc_eur', 'btc_chf', 'btc_gbp', 'ltc_btc', 'eth_btc')
MARKET_DISTANCES=range(1, 101)
DISTANCE_FILE_FORMAT='bisq_%d.txt'
NOW=time.time()

def get_bitcoin_average_headers():
    pub_key = os.getenv('BITCOIN_AVERAGE_PUB_KEY')
    sec_key = os.getenv('BITCOIN_AVERAGE_SEC_KEY')
    if not pub_key or not sec_key:
        raise(Exception('You must set BITCOIN_AVERAGE_PUB_KEY and BITCOIN_AVERAGE_SEC_KEY'))
    timestamp = int(NOW)
    payload = '{}.{}'.format(timestamp, pub_key)
    hex_hash = hmac.new(sec_key.encode(), msg=payload.encode(), digestmod=hashlib.sha256).hexdigest()
    signature = '{}.{}'.format(payload, hex_hash)
    return({'X-Signature': signature})

def get_bitcoin_average(from_cur, to_cur, headers):
    url = 'https://apiv2.bitcoinaverage.com/convert/global?from=%s&to=%s&amount=1' % (from_cur.upper(), to_cur.upper())
    return float(requests.get(url=url, headers=headers).json()['price'])

def process_offer(offer, market_price, distance, multiplier, sale):
    output = []
    price = float(offer['price'])
    distance_from_market_percent = ((price * multiplier) - market_price) / market_price * 100
    if not sale:
        distance_from_market_percent *= -1
    if distance_from_market_percent > distance:
        return []
    fiat = False
    if offer['payment_method'] != 'BLOCK_CHAINS':
        output.append('\tPayment method: %s' % offer['payment_method'])
        volume = offer['amount']
        fiat = True
    else:
        volume = offer['volume']
    output.append('\tOffer ID: %s' % (offer['offer_id'].split('-')[0]))
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
        
def write_offers(title, bisq_market, market_price, distance, output_file, multiplier):
    sell_offers = []
    for offer in bisq_market['sells']:
        output = process_offer(offer, market_price, distance, multiplier, True)
        if output:
            sell_offers.append(output)

    buy_offers = []
    for offer in bisq_market['buys']:
        output = process_offer(offer, market_price, distance, multiplier, False)
        if output:
            buy_offers.append(output)

    if sell_offers or buy_offers:
        output_file.write('%s' % title)
        if sell_offers:
            output_file.write('\nSells\n')
            output_file.write('\n\n'.join(['\n'.join(x) for x in sell_offers]))
        if buy_offers:
            output_file.write('\nBuys\n')
            output_file.write('\n\n'.join(['\n'.join(x) for x in buy_offers]))
        output_file.write('\n')
        return True
            
    return False

        
bitcoin_averages = {}
headers = get_bitcoin_average_headers()
for market in MARKETS:
    (src, dst) = market.split('_')
    if dst == 'btc':
        dst = 'usd'
    bitcoin_averages[market] = get_bitcoin_average(src, dst, headers)

bisq_markets = {}
for market in MARKETS:
    bisq_markets[market] = requests.get(get_bisq_url(market)).json()[market]

for distance in MARKET_DISTANCES:
    f = open(DISTANCE_FILE_FORMAT % (distance,), 'w')
    for market in MARKETS:
        (src, dst) = market.split('_')
        if dst == 'btc':
            dst = 'usd'
        f.write('Current %s price in %s: %.2f\n' % (src.upper(), dst.upper(), bitcoin_averages[market]))
    f.write('\n')

    for market in MARKETS:
        multiplier = 1
        (src, dst) = market.split('_')
        if dst == 'btc':
            multiplier = bitcoin_averages['btc_usd']
        written = write_offers('%s Offers with %s' % (src.upper(), dst.upper()), bisq_markets[market], bitcoin_averages[market], distance, f, multiplier)
        if written:
            f.write('\n')
        
    f.write('Last updated: %s\n' % (time.strftime('%c %Z', time.localtime(NOW))))
    f.write('Find this useful? Donations:\n')
    f.write('BTC: 1JM5NpCSNkiszS2zKJUtf8ZJinGbyJqYS1\n')
    f.write('ETH: 0x2cE131fa0385F4dA91d4542DD7D9Ca22988964FC\n')
    f.write('LTC: LKYt9emtttftRN2SEEpfnV1BsMvAUTCaUp\n')
    f.close()

