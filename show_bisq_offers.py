#!/usr/bin/env python3
#
# This creates 100 files in the current directory of the format bisq_N.txt where N is the maximum market distance percent.
# You must set environment variables BITCOIN_AVERAGE_PUB_KEY and BITCOIN_AVERAGE_SEC_KEY based on an API key for bitcoinaverage.com.
# You must pass a config file as the first argument.

import requests
import hashlib
import hmac
import json
import math
import time
import sys
import os
import smtplib
from email.mime.text import MIMEText

DOCS="""
Notes:

Market distance is defined differently based on the offer type. \
For "Sells", a negative market distance means the offer is to sell at less than the market price. \
For "Buys", a negative market distance means the offer is to buy at greater than the market price. \
This means that a negative (or low) distance is generally a good deal for both types.

Code for this tool is available at: https://github.com/valankar/arviraj

Find this useful? Please consider donating:
BTC: 1JM5NpCSNkiszS2zKJUtf8ZJinGbyJqYS1
ETH: 0x2cE131fa0385F4dA91d4542DD7D9Ca22988964FC
LTC: LKYt9emtttftRN2SEEpfnV1BsMvAUTCaUp
"""
CONFIG={}
MARKET_DISTANCES=range(1, 101)
NOW=time.time()

def send_notification(output, offer_id, payment_method, distance_from_market_percent, sale):
    global CONFIG
    if not CONFIG['smtp_server']:
        return
    for criteria in CONFIG['notifications']:
        if criteria['type'] == 'sell' and not sale:
            continue
        if criteria['payment_method'] != payment_method:
            continue
        if criteria['distance'] < distance_from_market_percent:
            continue
        sent_email = offer_id + ' ' + criteria['email']
        if sent_email in CONFIG['sent_notifications']:
            continue
        CONFIG['sent_notifications'][sent_email] = True
        msg = MIMEText('\n'.join(output))
        msg['Subject'] = CONFIG['notification_subject']
        msg['From'] = CONFIG['notification_from']
        msg['To'] = criteria['email']
        try:
            s = smtplib.SMTP(CONFIG['smtp_server'])
            s.sendmail(CONFIG['notification_from'], [criteria['email']], msg.as_string())
            s.quit()
        except:
            pass

def load_config():
    global CONFIG
    with open(sys.argv[1]) as config_file:
        CONFIG = json.load(config_file)
    try:
        with open(CONFIG['notification_state_file']) as f:
            CONFIG['sent_notifications'] = json.load(f)
    except:
        CONFIG['sent_notifications'] = {}

def save_notification_state():
    with open(CONFIG['notification_state_file'], 'w') as f:
        json.dump(CONFIG['sent_notifications'], f, indent=2, sort_keys=True)
      
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

def get_bisq_tx_fee():
    return int(requests.get(url='http://37.139.14.34:8080/getFees').json()['dataMap']['btcTxFee'])
TX_FEE=get_bisq_tx_fee()
    
def get_fees(amount, distance):
    fee = TX_FEE * 200/100000000.
    maker = max(0.0002, 0.002 * amount * math.sqrt(distance)) + fee
    taker = max(0.0002, 0.003 * amount) + (3 * fee)
    return (maker, taker)
    
def get_range_or_value(first, second, format_str):
    if first == second:
        return format_str % (first,)
    else:
        return (format_str + ' - ' + format_str) % (first, second)

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
    output.append('\tAmount in BTC: %s' % (get_range_or_value(float(offer['min_amount']), float(volume), '%s')))
    min_fee = get_fees(float(offer['min_amount']), abs(distance_from_market_percent))
    max_fee = get_fees(float(volume), abs(distance_from_market_percent))
    output.append('\tMaker fee in BTC: %s' % (get_range_or_value(min_fee[0], max_fee[0], '%f')))
    output.append('\tTaker fee in BTC: %s' % (get_range_or_value(min_fee[1], max_fee[1], '%f')))
    if fiat:
        output.append('\tPrice for 1: %.2f' % price)
        output.append('\tMaximum: %.2f' % (price * float(volume)))
    else:
        output.append('\tPrice for 1 in USD: %.2f' % (price * multiplier))
        output.append('\tMaximum in USD: %.2f' % (multiplier * float(volume)))
    output.append('\tDistance from market: %.2f%%' % distance_from_market_percent)
    send_notification(output, offer['offer_id'], offer['payment_method'], distance_from_market_percent, sale)
    return output
    
def get_human_readable_time(seconds):
    d = int(seconds / (60 * 60 * 24))
    h = int((seconds % (60 * 60 * 24)) / (60 * 60))
    m = int((seconds % (60 * 60)) / 60)
    s = seconds % 60
    if d:
        return '%dd' % d
    if h:
        return '%dh' % h
    if m:
        return '%dm' % m
    return '%ds' % s
    
def get_last_trade(bisq_last_trade, market_price, multiplier):
    price = float(bisq_last_trade['price'])
    age = get_human_readable_time(NOW - int(bisq_last_trade['trade_date'] / 1000))
    distance_from_market_percent = ((price * multiplier) - market_price) / market_price * 100
    if multiplier == 1:
        price_text = ': %.2f' % (price,)
    else:
        price_text = ' in USD: %.2f' % (price * multiplier,)
    text = 'Last trade price for 1%s, Distance from current market: %.2f%%, Age: %s' % (price_text, distance_from_market_percent, age)
    return text

def write_offers(output_file, bisq_market, market_price, distance, multiplier):
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
        if sell_offers:
            output_file.write('\nSells\n')
            output_file.write('\n\n'.join(['\n'.join(x) for x in sell_offers]))
        if buy_offers:
            output_file.write('\nBuys\n')
            output_file.write('\n\n'.join(['\n'.join(x) for x in buy_offers]))

    output_file.write('\n')

def get_bisq_market_url(market):
    return('https://market.bisq.io/api/offers?market=%s' % (market,))

def get_bisq_last_trade_url(market):
    return('https://market.bisq.io/api/trades?market=%s&limit=1' % (market,))


load_config()
bitcoin_averages = {}
headers = get_bitcoin_average_headers()
for market in CONFIG['markets']:
    (src, dst) = market.split('_')
    if dst == 'btc':
        dst = 'usd'
    bitcoin_averages[market] = get_bitcoin_average(src, dst, headers)

bisq_markets = {}
bisq_last_trades = {}
for market in CONFIG['markets']:
    bisq_markets[market] = requests.get(get_bisq_market_url(market)).json()[market]
    bisq_last_trades[market] = requests.get(get_bisq_last_trade_url(market)).json()[0]

for distance in MARKET_DISTANCES:
    f = open(CONFIG['distance_file_format'] % (distance,), 'w')
    for market in CONFIG['markets']:
        (src, dst) = market.split('_')
        if dst == 'btc':
            dst = 'usd'
        f.write('Current %s price in %s: %.2f\n' % (src.upper(), dst.upper(), bitcoin_averages[market]))
    f.write('\nBisq offers with market distance < %d%%\n\n' % (distance,))

    for market in CONFIG['markets']:
        multiplier = 1
        (src, dst) = market.split('_')
        if dst == 'btc':
            multiplier = bitcoin_averages['btc_usd']
        last_trade = get_last_trade(bisq_last_trades[market], bitcoin_averages[market], multiplier)
        f.write('%s Offers with %s (%s)' % (src.upper(), dst.upper(), last_trade))
        write_offers(f, bisq_markets[market], bitcoin_averages[market], distance, multiplier)
        f.write('\n')
        
    f.write('Last updated: %s\n' % (time.strftime('%c %Z', time.localtime(NOW))))
    f.writelines(DOCS)
    f.close()

save_notification_state()
