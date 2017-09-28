#!/usr/bin/env python3
#
# This creates 100 files in the current directory of the format bisq_N.txt where N is the maximum market distance percent.
# You must pass a config file as the first argument.

import requests
import hashlib
import hmac
import json
import math
import time
import sys
import re
import smtplib
import twitter
from email.mime.text import MIMEText
from babel import numbers

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
CURRENCY_FORMAT=u'###0.00 ¤¤'


def send_twitter_notification(output, offer_id, criteria, trade_type):
    global CONFIG
    sent = offer_id + ' twitter ' + criteria['consumer_key']
    if sent in CONFIG['sent_notifications']:
       return
    CONFIG['sent_notifications'][sent] = True
    api = twitter.Api(consumer_key=criteria['consumer_key'],
                      consumer_secret=criteria['consumer_secret'],
                      access_token_key=criteria['access_token'],
                      access_token_secret=criteria['access_token_secret'])
    condensed = [trade_type]
    for line in output:
        if 'fee:' in line:
            continue
        line = line.replace(' from market', '')
        condensed.append(re.sub(r'\s+', ' ', line.strip()))
    tweet = '\n'.join(condensed)[:140]
    try:
        api.PostUpdate(tweet, verify_status_length=False)
    except:
        pass

def send_email_notification(output, offer_id, criteria, trade_type):
    global CONFIG
    sent = offer_id + ' email ' + criteria['email']
    if sent in CONFIG['sent_notifications']:
        return
    CONFIG['sent_notifications'][sent] = True
    msg = MIMEText('\n'.join([trade_type] + output))
    msg['Subject'] = criteria['subject']
    msg['From'] = criteria['from']
    msg['To'] = criteria['email']
    try:
        s = smtplib.SMTP(criteria['smtp_server'])
        s.sendmail(criteria['from'], [criteria['email']], msg.as_string())
        s.quit()
    except:
        pass

def send_notification(output, offer_id, payment_method, distance_from_market_percent, sale):
    global CONFIG
    for criteria in CONFIG['notifications']:
        if sale:
            trade_type = 'SELL'
            if 'sell' not in criteria['type']:
                continue
        else:
            trade_type = 'BUY'
            if 'buy' not in criteria['type']:
                continue
        if payment_method not in criteria['payment_method']:
            continue
        if criteria['distance'] < distance_from_market_percent:
            continue
        method = criteria['notification_method']
        if method == 'email':
            send_email_notification(output, offer_id, criteria, trade_type)
        elif method == 'twitter':
            send_twitter_notification(output, offer_id, criteria, trade_type)

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
    pub_key = CONFIG['bitcoin_average_public_key']
    sec_key = CONFIG['bitcoin_average_secret_key']
    timestamp = int(NOW)
    payload = '{}.{}'.format(timestamp, pub_key)
    hex_hash = hmac.new(sec_key.encode(), msg=payload.encode(), digestmod=hashlib.sha256).hexdigest()
    signature = '{}.{}'.format(payload, hex_hash)
    return({'X-Signature': signature})

def get_bitcoin_average(from_cur, to_cur, headers):
    url = 'https://apiv2.bitcoinaverage.com/convert/global?from={}&to={}&amount=1'.format(from_cur.upper(), to_cur.upper())
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
        return format_str.format(first)
    else:
        return (format_str + ' - ' + format_str).format(first, second)

def shorten_trade_id(trade_id):
    return trade_id.split('-')[0]

def format_currency(value, currency):
    return numbers.format_currency(value, currency, CURRENCY_FORMAT)

def process_offer(offer, currency, market_price, distance, multiplier, sale):
    output = []
    price = float(offer['price'])
    distance_from_market_percent = ((price * multiplier) - market_price) / market_price * 100
    if not sale:
        distance_from_market_percent *= -1
    if distance_from_market_percent > distance:
        return []
    fiat = False
    if offer['payment_method'] != 'BLOCK_CHAINS':
        output.append('\tPayment method: {}'.format(offer['payment_method']))
        volume = offer['amount']
        fiat = True
    else:
        volume = offer['volume']
    output.append('\tOffer ID: {}'.format(shorten_trade_id(offer['offer_id'])))
    output.append('\tAmount: {} BTC'.format(get_range_or_value(float(offer['min_amount']), float(volume), '{}')))
    min_fee = get_fees(float(offer['min_amount']), abs(distance_from_market_percent))
    max_fee = get_fees(float(volume), abs(distance_from_market_percent))
    output.append('\tMaker fee: {} BTC'.format(get_range_or_value(min_fee[0], max_fee[0], '{:f}')))
    output.append('\tTaker fee: {} BTC'.format(get_range_or_value(min_fee[1], max_fee[1], '{:f}')))
    if fiat:
        output.append('\tPrice for 1: {}'.format(format_currency(price, currency)))
        output.append('\tMaximum: {}'.format(format_currency(price * float(volume), currency)))
    else:
        output.append('\tPrice for 1: {}'.format(format_currency(price * multiplier, 'USD')))
        output.append('\tMaximum: {}'.format(format_currency(multiplier * float(volume), 'USD')))
    output.append('\tDistance from market: {:.2f}%'.format(distance_from_market_percent))
    send_notification(output, offer['offer_id'], offer['payment_method'], distance_from_market_percent, sale)
    return output
    
def get_human_readable_time(seconds):
    d = int(seconds / (60 * 60 * 24))
    h = int((seconds % (60 * 60 * 24)) / (60 * 60))
    m = int((seconds % (60 * 60)) / 60)
    s = int(seconds % 60)
    if d:
        return '{:d}d'.format(d)
    if h:
        return '{:d}h'.format(h)
    if m:
        return '{:d}m'.format(m)
    return '{:d}s'.format(s)
    
def get_last_trade(bisq_last_trade, market_price, multiplier):
    price = float(bisq_last_trade['price'])
    trade_id = shorten_trade_id(bisq_last_trade['trade_id'])
    age = get_human_readable_time(NOW - int(bisq_last_trade['trade_date'] / 1000))
    distance_from_market_percent = ((price * multiplier) - market_price) / market_price * 100
    if multiplier == 1:
        price_text = ': {:.2f}'.format(price)
    else:
        price_text = ' in USD: {:.2f}'.format(price * multiplier)
    text = 'Last trade (ID: {}) price for 1{}, Distance from current market: {:.2f}%, Age: {}'.format(
            trade_id, price_text, distance_from_market_percent, age)
    return text

def write_offers(output_file, currency, bisq_market, market_price, distance, multiplier):
    sell_offers = []
    for offer in bisq_market['sells']:
        output = process_offer(offer, currency, market_price, distance, multiplier, True)
        if output:
            sell_offers.append(output)

    buy_offers = []
    for offer in bisq_market['buys']:
        output = process_offer(offer, currency, market_price, distance, multiplier, False)
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
    return('https://market.bisq.io/api/offers?market={}'.format(market))

def get_bisq_last_trade_url(market):
    return('https://market.bisq.io/api/trades?market={}&limit=1'.format(market))


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
    f = open(CONFIG['distance_file_format'].format(distance), 'w')
    for market in CONFIG['markets']:
        (src, dst) = market.split('_')
        if dst == 'btc':
            dst = 'usd'
        f.write('Current {} price in {}: {:.2f}\n'.format(src.upper(), dst.upper(), bitcoin_averages[market]))
    f.write('\nBisq offers with market distance < {:d}%\n\n'.format(distance))

    for market in CONFIG['markets']:
        multiplier = 1
        (src, dst) = market.split('_')
        if dst == 'btc':
            multiplier = bitcoin_averages['btc_usd']
        last_trade = get_last_trade(bisq_last_trades[market], bitcoin_averages[market], multiplier)
        f.write('{} Offers with {} ({})'.format(src.upper(), dst.upper(), last_trade))
        write_offers(f, dst.upper(), bisq_markets[market], bitcoin_averages[market], distance, multiplier)
        f.write('\n')
        
    f.write('Last updated: {}\n'.format(time.strftime('%c %Z', time.localtime(NOW))))
    f.writelines(DOCS)
    f.close()

save_notification_state()
